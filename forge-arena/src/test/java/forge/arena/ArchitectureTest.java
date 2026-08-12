package forge.arena;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import org.testng.annotations.Test;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.core.importer.ImportOption;

/**
 * W2/W8 enforcement (plan §4/§9): only the two sanctioned seams may touch
 * Forge game internals — {@code forge.arena.engine} (headless harness, via
 * EngineFacade) and {@code forge.arena.interactive} (live-game mailbox seats,
 * whose PlayerController/LobbyPlayer implementations cannot route through the
 * facade). When a rebase renames engine classes, the blast radius must stay
 * inside those packages.
 */
public class ArchitectureTest {

    @Test
    public void onlyEnginePackageImportsForgeGameInternals() {
        JavaClasses arenaClasses = new ClassFileImporter()
                .withImportOption(new ImportOption.DoNotIncludeTests())
                .importPackages("forge.arena");

        noClasses()
                .that().resideInAPackage("forge.arena..")
                .and().resideOutsideOfPackage("forge.arena.engine..")
                .and().resideOutsideOfPackage("forge.arena.interactive..")
                .should().dependOnClassesThat()
                .resideInAnyPackage("forge.game..", "forge.ai..", "forge.deck..", "forge.item..", "forge.player..")
                .because("EngineFacade is the single import point for Forge internals for the headless"
                        + " harness (plan §4, W2); forge.arena.interactive is the sanctioned live-game"
                        + " seam (mailbox seats implement PlayerController/LobbyPlayer directly)")
                .check(arenaClasses);
    }

    @Test
    public void comboLayerMayTouchOnlySeatViewFromTheEngine() {
        JavaClasses arenaClasses = new ClassFileImporter()
                .withImportOption(new ImportOption.DoNotIncludeTests())
                .importPackages("forge.arena");

        noClasses()
                .that().resideInAPackage("forge.arena.combo..")
                .should().dependOnClassesThat(new com.tngtech.archunit.base.DescribedPredicate<>(
                        "engine classes other than SeatView (the W8 read-model)") {
                    @Override
                    public boolean test(com.tngtech.archunit.core.domain.JavaClass input) {
                        // exact match + nested (SeatView$Zone) — a bare startsWith would
                        // wrongly exempt SeatViews, the Forge-importing factory
                        return input.getPackageName().startsWith("forge.arena.engine")
                                && !input.getFullName().equals("forge.arena.engine.SeatView")
                                && !input.getFullName().startsWith("forge.arena.engine.SeatView$");
                    }
                })
                .because("combo/ consumes SeatView ONLY — never Game, never the facade (plan §6/§9 W8)")
                .check(arenaClasses);
    }
}
