package forge.arena;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import org.testng.annotations.Test;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.core.importer.ImportOption;

/**
 * W2/W8 enforcement (plan §4/§9): only {@code forge.arena.engine} may touch
 * Forge game internals. When a rebase renames engine classes, the blast radius
 * must stay one package.
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
                .should().dependOnClassesThat()
                .resideInAnyPackage("forge.game..", "forge.ai..", "forge.deck..", "forge.item..", "forge.player..")
                .because("EngineFacade is the single import point for Forge internals (plan §4, W2)")
                .check(arenaClasses);
    }
}
