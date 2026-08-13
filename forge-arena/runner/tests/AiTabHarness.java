import java.io.File;
import java.nio.file.Files;
import forge.arena.interactive.AiControlFile;

/** Headless test of the AI tab's real control-file logic (no Swing).
 *  Covers the backend-model additions (plan v5 §7): lazy models() property
 *  injection, the non-destructive step() on out-of-cycle values, and the
 *  narrow-column display form. Compile against forge-gui-desktop classes:
 *    javac -cp <gui-desktop classes> AiTabHarness.java && java -cp . AiTabHarness
 */
public class AiTabHarness {
    static int fails = 0;
    static void check(boolean ok, String msg) { if (!ok) { System.out.println("FAIL: " + msg); fails++; } }

    public static void main(String[] args) throws Exception {
        File tmp = Files.createTempDirectory("aitab").toFile();
        System.setProperty("arena.runner.logs.dir", tmp.getAbsolutePath());
        System.clearProperty("arena.extra.models");
        new File(tmp, "control").mkdirs();
        File ctl = AiControlFile.controlFile(2);

        // model ++++ from default -> sonnet,opus,fable, clamp at fable
        AiControlFile.step(2, true, +1);
        AiControlFile.step(2, true, +1);
        AiControlFile.step(2, true, +1);
        AiControlFile.step(2, true, +1);
        System.out.println("after model++++ : " + new String(Files.readAllBytes(ctl.toPath())));
        check("fable".equals(AiControlFile.model(2, "?")), "model should clamp at fable");

        // effort + (low->medium), model preserved
        AiControlFile.step(2, false, +1);
        check("medium".equals(AiControlFile.effort(2, "?")), "effort should be medium");
        check("fable".equals(AiControlFile.model(2, "?")), "model must be preserved across effort step");

        // model - (fable->opus)
        AiControlFile.step(2, true, -1);
        check("opus".equals(AiControlFile.model(2, "?")), "model should step down to opus");

        // effort - - clamps at low
        AiControlFile.step(2, false, -1);
        AiControlFile.step(2, false, -1);
        check("low".equals(AiControlFile.effort(2, "?")), "effort should clamp at low");

        // file shape is exactly what the runner + arena-ctl honor (model may
        // carry / : . - for backend strings, hence [^"]+ not \w+)
        String body = new String(Files.readAllBytes(ctl.toPath())).trim();
        check(body.matches("\\{\"model\": \"[^\"]+\", \"effort\": \"[^\"]+\"\\}"), "runner-compatible shape: " + body);

        // extra models: lazy models() picks the property up at call time
        check(AiControlFile.models().length == 4, "default cycle is the 4 claude names");
        System.setProperty("arena.extra.models", "or/google/gemini-2.5-pro,oai/mistral-7b,bad\"entry");
        String[] cycle = AiControlFile.models();
        check(cycle.length == 6, "extra models join the cycle (bad entry filtered), got " + cycle.length);
        check("or/google/gemini-2.5-pro".equals(cycle[4]), "or/ entry appended in order");

        // with the property set, stepping past fable reaches the or/ entry
        AiControlFile.step(2, true, +1); // opus -> fable
        AiControlFile.step(2, true, +1); // fable -> or/google/gemini-2.5-pro
        check("or/google/gemini-2.5-pro".equals(AiControlFile.model(2, "?")),
                "stepper reaches backend entries when the property is set");

        // effort step preserves a backend model string byte-for-byte
        AiControlFile.step(2, false, +1);
        check("or/google/gemini-2.5-pro".equals(AiControlFile.model(2, "?")),
                "effort step must not disturb a backend model string");

        // non-destructive step (plan F-11): without the property, the or/
        // value is out-of-cycle and a model step must be a byte-level no-op
        System.clearProperty("arena.extra.models");
        String before = new String(Files.readAllBytes(ctl.toPath()));
        AiControlFile.step(2, true, -1);
        String after = new String(Files.readAllBytes(ctl.toPath()));
        check(before.equals(after), "step on out-of-cycle model must not rewrite the file");

        // canStep mirrors step()'s no-op logic — the panel hides dead buttons
        check(!AiControlFile.canStep(2, true, -1), "out-of-cycle model: minus is dead");
        check(!AiControlFile.canStep(2, true, +1), "out-of-cycle model: plus is dead");
        AiControlFile.write(2, "haiku", "low");
        check(!AiControlFile.canStep(2, true, -1), "clamped at haiku: minus is dead");
        check(AiControlFile.canStep(2, true, +1), "haiku: plus is live");
        check(!AiControlFile.canStep(2, false, -1), "clamped at low effort: minus is dead");
        AiControlFile.write(2, "or/google/gemini-2.5-pro", "low");

        // display form for the narrow model column
        check("or:gemini-2.5-pro".equals(AiControlFile.displayModel("or/google/gemini-2.5-pro")), "or/ display form");
        check("oai:mistral-7b".equals(AiControlFile.displayModel("oai/mistral-7b")), "oai/ display form");
        check("opus".equals(AiControlFile.displayModel("opus")), "claude names pass through");

        // liveness: no usage file -> offline (huge age); fresh file -> small age
        check(AiControlFile.usageAgeMillis(2) > 300_000, "no usage file => offline");
        Files.write(AiControlFile.usageFile(2).toPath(), "{}".getBytes());
        check(AiControlFile.usageAgeMillis(2) < 60_000, "fresh usage file => live");

        System.out.println(fails == 0 ? "ALL PASS — AI tab control logic verified headless" : fails + " FAILURES");
        System.exit(fails);
    }
}
