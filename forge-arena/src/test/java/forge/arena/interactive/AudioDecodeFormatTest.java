package forge.arena.interactive;

import java.io.ByteArrayInputStream;
import java.io.File;

import javax.sound.sampled.AudioFormat;
import javax.sound.sampled.AudioInputStream;
import javax.sound.sampled.AudioSystem;

import org.testng.Assert;
import org.testng.annotations.Test;

/**
 * BL-56 (2026-09-17): the arbiter for the {@code [arena]} patch in
 * {@code forge.sound.AudioClip.getAudioClips}. Forge's MP3 converter emits 8-bit unsigned PCM by
 * default, which forces Java Sound's software mixer (impulses, held samples, overlapping effects
 * summed to overload) and a 48 dB quantization floor — the pop and crackle Ben heard on the shuffle
 * and the opening draws. The patch asks the converter for 16-bit signed PCM, which takes the direct
 * device line. This test reads the decoded bytes and needs no audio device (Ben: no long-term test
 * may require the loopback); the measurement that found the defect lives in
 * {@code forge-arena/scripts/research/sound/} as manual research.
 */
public class AudioDecodeFormatTest {

    private static final File SOUND = new File("..", "forge-gui/res/sound");

    @Test
    public void effectsDecodeToSixteenBitSignedPcm() throws Exception {
        // button_press (32 kHz) and coins_drop (48 kHz) are the sources the converter resamples; all 39 are stereo, downmixed
        for (String name : new String[] {"draw", "shuffle", "tap", "nighttime", "button_press", "coins_drop"}) {
            final File mp3 = new File(SOUND, name + ".mp3");
            Assert.assertTrue(mp3.isFile(), mp3 + " (the test runs from forge-arena/, like the others)");
            final byte[] wav = forge.sound.AudioClip.getAudioClips(mp3);
            try (AudioInputStream in = AudioSystem.getAudioInputStream(new ByteArrayInputStream(wav))) {
                final AudioFormat f = in.getFormat();
                Assert.assertEquals(f.getSampleSizeInBits(), 16, name + ": 8-bit decodes go through the software mixer and crackle (BL-56)");
                Assert.assertEquals(f.getEncoding(), AudioFormat.Encoding.PCM_SIGNED, name);
                Assert.assertEquals(f.getChannels(), 1, name);
                Assert.assertEquals((int) f.getSampleRate(), 44100, name);
                Assert.assertTrue(in.getFrameLength() > 0, name + ": decoded to nothing");
                Assert.assertEquals(in.getFrameLength() * f.getFrameSize(), (long) in.available(),
                        name + ": the header must say what the data holds (the converter wrote the byte count as the frame count)");
            }
        }
    }
}
