import java.io.File;
import java.nio.file.Files;
import forge.arena.interactive.AiControlFile;

/** Headless test of the AI tab's real control-file logic (no Swing). */
public class AiTabHarness {
    static int fails = 0;
    static void check(boolean ok, String msg) { if (!ok) { System.out.println("FAIL: " + msg); fails++; } }

    public static void main(String[] args) throws Exception {
        File tmp = Files.createTempDirectory("aitab").toFile();
        System.setProperty("arena.runner.logs.dir", tmp.getAbsolutePath());
        new File(tmp, "control").mkdirs();
        File ctl = AiControlFile.controlFile(2);

        // model +++ from default -> haiku,sonnet,opus, clamp at opus
        AiControlFile.step(2, true, +1);
        AiControlFile.step(2, true, +1);
        AiControlFile.step(2, true, +1);
        System.out.println("after model+++ : " + new String(Files.readAllBytes(ctl.toPath())));
        check("opus".equals(AiControlFile.model(2, "?")), "model should clamp at opus");

        // effort + (low->medium), model preserved
        AiControlFile.step(2, false, +1);
        System.out.println("after effort+  : " + new String(Files.readAllBytes(ctl.toPath())));
        check("medium".equals(AiControlFile.effort(2, "?")), "effort should be medium");
        check("opus".equals(AiControlFile.model(2, "?")), "model must be preserved across effort step");

        // model - (opus->sonnet)
        AiControlFile.step(2, true, -1);
        check("sonnet".equals(AiControlFile.model(2, "?")), "model should step down to sonnet");

        // effort - - clamps at low
        AiControlFile.step(2, false, -1);
        AiControlFile.step(2, false, -1);
        check("low".equals(AiControlFile.effort(2, "?")), "effort should clamp at low");

        // file shape is exactly what the runner + arena-ctl honor
        String body = new String(Files.readAllBytes(ctl.toPath())).trim();
        check(body.matches("\\{\"model\": \"\\w+\", \"effort\": \"\\w+\"\\}"), "runner-compatible shape: " + body);

        // liveness: no usage file -> offline (huge age); fresh file -> small age
        check(AiControlFile.usageAgeMillis(2) > 300_000, "no usage file => offline");
        Files.write(AiControlFile.usageFile(2).toPath(), "{}".getBytes());
        check(AiControlFile.usageAgeMillis(2) < 60_000, "fresh usage file => live");

        System.out.println(fails == 0 ? "ALL PASS — AI tab control logic verified headless" : fails + " FAILURES");
        System.exit(fails);
    }
}
