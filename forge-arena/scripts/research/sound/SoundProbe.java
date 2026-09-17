import java.io.*;
import java.nio.file.*;
import java.util.*;
import javax.sound.sampled.*;

/** Plays Forge's effects through the SAME JavaSound calls Forge makes (mode clip = forge.sound.AudioClip's
 *  ClipWrapper; mode alt = forge.sound.AltSoundSystem's streaming SourceDataLine), or through afplay as a baseline.
 *  Sequence: shuffle x3, the opening draw x7 at 120 ms, then every asset once. Logs one JSON line per play. */
public class SoundProbe {
    static Map<String, byte[]> wav = new HashMap<>();
    static Map<String, List<Clip>> pool = new HashMap<>();
    static PrintWriter log;
    static String mode;
    static Path tmp;

    public static void main(String[] a) throws Exception {
        mode = a[0]; File dir = new File(a[1]); log = new PrintWriter(new FileWriter(a[2]));
        tmp = Files.createTempDirectory("probe");
        List<String> names = new ArrayList<>();
        for (File f : Objects.requireNonNull(dir.listFiles((d, n) -> n.endsWith(".mp3")))) names.add(f.getName().replace(".mp3", ""));
        Collections.sort(names);
        boolean conv16 = mode.endsWith("C16");                 // the candidate one-line fix: Forge's own converter asked for 16-bit
        boolean sixteen = !conv16 && mode.endsWith("16");      // the experiment: the same clip path fed 16-bit WAV instead of Forge's 8-bit decode
        if (conv16) mode = mode.substring(0, mode.length() - 3);
        else if (sixteen) mode = mode.substring(0, mode.length() - 2);
        AudioFormat target = new AudioFormat(44100f, 16, 1, true, false);
        for (String n : names) {
            byte[] b;
            if (conv16) b = com.sipgate.mp3wav.Converter.convertFrom(new FileInputStream(new File(dir, n + ".mp3"))).withTargetFormat(target).toByteArray();
            else if (sixteen) b = Files.readAllBytes(Paths.get(a[2]).getParent().resolve("src16").resolve(n + ".wav"));
            else b = forge.sound.AudioClip.getAudioClips(new File(dir, n + ".mp3"));   // Forge's own mp3 -> wav bytes
            wav.put(n, b);
        }
        if (conv16) { AudioInputStream chk = AudioSystem.getAudioInputStream(new ByteArrayInputStream(wav.get("draw"))); System.err.println("conv16 format: " + chk.getFormat()); }
        if (mode.equals("dump")) {                      // the decoded sources, for the residual comparison
            Path out = Paths.get(a[2]).getParent().resolve("src"); Files.createDirectories(out);
            for (String n : names) Files.write(out.resolve(n + ".wav"), wav.get(n));
            System.exit(0);
        }
        Thread.sleep(800);
        if (a.length > 3 && a[3].equals("burst")) {
            for (int b = 0; b < 3; b++) { for (int i = 0; i < 7; i++) { play("draw", b * 10 + i); Thread.sleep(120); } Thread.sleep(2200); }
            play("nighttime", 0); Thread.sleep(4200);
            play("mana_burn", 0); Thread.sleep(2600);
            play("shuffle", 0); Thread.sleep(1800);
        } else {
            for (int i = 0; i < 3; i++) { play("shuffle", i); Thread.sleep(1500); }
            for (int i = 0; i < 7; i++) { play("draw", i); Thread.sleep(120); }
            Thread.sleep(1500);
            for (String n : names) { play(n, 0); Thread.sleep(1000); }
        }
        Thread.sleep(2500);
        log.close();
        System.exit(0);
    }

    static void play(String name, int rep) throws Exception {
        long t = System.currentTimeMillis();
        switch (mode) {
            case "clip" -> playClip(name);
            case "alt" -> playAlt(name);
            case "afplay" -> playAfplay(name);
            default -> throw new IllegalArgumentException(mode);
        }
        log.println("{\"name\": \"" + name + "\", \"rep\": " + rep + ", \"t_ms\": " + t + ", \"mode\": \"" + mode + "\"}");
        log.flush();
    }

    // forge.sound.AudioClip.ClipWrapper: a Clip per asset, more when they overlap; rewind + start per play
    static void playClip(String name) throws Exception {
        List<Clip> clips = pool.computeIfAbsent(name, k -> new ArrayList<>());
        Clip idle = null;
        for (Clip c : clips) if (!c.isRunning() && !c.isActive()) { idle = c; break; }
        if (idle == null) {
            AudioInputStream s = AudioSystem.getAudioInputStream(new ByteArrayInputStream(wav.get(name)));
            AudioFormat f = s.getFormat();
            DataLine.Info info = new DataLine.Info(Clip.class, f, (int) s.getFrameLength() * f.getFrameSize());
            idle = (Clip) AudioSystem.getLine(info);
            idle.open(s);
            clips.add(idle);
        }
        final Clip c = idle;
        synchronized (c) { c.setMicrosecondPosition(0); c.start(); }
    }

    // forge.sound.AltSoundSystem: one streaming SourceDataLine per play, 512 KB buffer, drain, close
    static void playAlt(String name) {
        byte[] data = wav.get(name);
        Thread th = new Thread(() -> {
            try {
                AudioInputStream s = AudioSystem.getAudioInputStream(new ByteArrayInputStream(data));
                AudioFormat f = s.getFormat();
                SourceDataLine line = AudioSystem.getSourceDataLine(f);
                line.open(f);
                line.start();
                byte[] buf = new byte[524288]; int n;
                while ((n = s.read(buf, 0, buf.length)) != -1) line.write(buf, 0, n);
                line.drain(); line.close();
            } catch (Exception e) { System.err.println("alt " + name + ": " + e); }
        });
        th.start();
    }

    static void playAfplay(String name) throws Exception {
        Path p = tmp.resolve(name + ".wav");
        if (!Files.exists(p)) Files.write(p, wav.get(name));
        new ProcessBuilder("afplay", p.toString()).inheritIO().start();
    }
}
