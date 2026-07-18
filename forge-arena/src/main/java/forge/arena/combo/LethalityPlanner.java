package forge.arena.combo;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import forge.arena.engine.SeatView;
import forge.arena.report.ArenaEvent;

/**
 * LethalityPlanner v1 (plan §6 v3.1/v3.2, PR-16): infinite resources are not
 * a win — this decides HOW they convert, from the deck's prep-computed
 * {@link RoutePlan} plus live public information, and RECORDS every
 * evaluation: each considered route emits {@code route_selected} or
 * {@code route_rejected} with the predicate values that decided it (plan §5:
 * silence is never a valid record of a decision).
 *
 * <p>Selection order per WIN-ROUTES §1: same-turn terminal routes first,
 * least interactable first. v1 predicates are deliberately coarse — the
 * planner selects the route and the shortcut-funded stock AI converts; the
 * scripted DEPLOY_WIN stage replaces stock conversion in a later PR.
 * BANK_AND_HOLD is the explicit non-route: always available, always last,
 * and its selection means every real route said no (their rejections say
 * why — Gate 3.6's stall autopsy feeds on exactly this trace).
 */
public final class LethalityPlanner {

    /** Evaluation order: same-turn terminals, least interactable first. */
    private static final List<String> PREFERENCE = List.of(
            "ORACLE_WIN", "DIRECT_DAMAGE_LOOP", "SPREAD_COMBAT", "COMMANDER_DMG_SEQUENCE");

    public record Verdict(String route, Map<String, Object> predicates) {
    }

    private LethalityPlanner() {
    }

    /**
     * Choose the win route for a seat whose loop just proved infinite mana.
     * Every route in the plan that gets considered emits its telemetry; the
     * returned verdict is what {@code route_selected} recorded.
     */
    public static Verdict choose(RoutePlan plan, SeatView view, Consumer<ArenaEvent> events) {
        long tableLife = view.opponents().stream().mapToLong(SeatView.OpponentView::life).sum();

        for (String routeName : PREFERENCE) {
            RoutePlan.PlannedRoute route = plan.route(routeName).orElse(null);
            if (route == null || !route.expressible()) {
                continue; // never made the deck's plan — not a live decision
            }
            Map<String, Object> predicates = new LinkedHashMap<>();
            String failed = evaluate(routeName, plan, view, tableLife, predicates);
            if (failed == null) {
                events.accept(event("route_selected", view, routeName, predicates, null));
                return new Verdict(routeName, predicates);
            }
            events.accept(event("route_rejected", view, routeName, predicates, failed));
        }

        Map<String, Object> predicates = new LinkedHashMap<>();
        predicates.put("note", "all real routes rejected — shortcut pool banked for interaction");
        events.accept(event("route_selected", view, "BANK_AND_HOLD", predicates, null));
        return new Verdict("BANK_AND_HOLD", predicates);
    }

    /** Null = route holds; otherwise the name of the failed predicate. */
    private static String evaluate(String routeName, RoutePlan plan, SeatView view,
            long tableLife, Map<String, Object> predicates) {
        switch (routeName) {
            case "ORACLE_WIN": {
                String enabler = firstVisible(plan.payoffCards("oracle_win"), view);
                predicates.put("oracle_enabler", enabler);
                return enabler != null ? null : "oracle_effect_not_visible";
            }
            case "DIRECT_DAMAGE_LOOP": {
                String sink = firstVisible(plan.payoffCards("x_damage"), view);
                if (sink == null) {
                    sink = firstVisible(plan.payoffCards("ping_each_opponent"), view);
                }
                if (sink == null) {
                    sink = firstVisible(plan.payoffCards("ping_any_target"), view);
                }
                predicates.put("damage_sink", sink);
                predicates.put("table_life", tableLife);
                return sink != null ? null : "damage_sink_not_visible";
            }
            case "SPREAD_COMBAT": {
                // PR-25 haste v2: a static grant anywhere visible, a one-shot
                // (Finale class) IN HAND — castable off the proven pool — or
                // an ETB-haste permanent ON BATTLEFIELD (Surrak class: every
                // DEPLOYED attacker enters hasty; the stall autopsies showed
                // haste_source_not_visible was every SPREAD rejection)
                String haste = firstVisible(plan.payoffCards("haste_static"), view);
                String hasteKind = haste != null ? "static" : null;
                if (haste == null) {
                    haste = firstIn(plan.payoffCards("haste_oneshot"), view,
                            SeatView.Presence.HAND);
                    hasteKind = haste != null ? "oneshot_in_hand" : null;
                }
                if (haste == null) {
                    haste = firstIn(plan.payoffCards("haste_targeted"), view,
                            SeatView.Presence.BATTLEFIELD);
                    hasteKind = haste != null ? "targeted_on_battlefield" : null;
                }
                // PR-41 haste v3 (the 300-game funnel): SPREAD_COMBAT was
                // REJECTED 99 times against 26 selections for the green deck,
                // every rejection haste_source_not_visible, while Lightning
                // Greaves sat in HAND and a thousand mana sat in the pool.
                //
                // The long-deferred haste split, now forced by evidence: an
                // EQUIPMENT grant works from hand off a banked pool (cast it,
                // equip it, the creature already on board attacks this turn),
                // whereas an ETB-trigger granter only hastens creatures that
                // enter AFTER it and is therefore worthless in hand for an
                // army already deployed. One class, two different truths.
                if (haste == null) {
                    haste = firstIn(plan.payoffCards("haste_equip"), view,
                            SeatView.Presence.HAND);
                    hasteKind = haste != null ? "equip_castable" : null;
                }
                if (haste == null) {
                    haste = firstVisible(plan.payoffCards("haste_equip"), view);
                    hasteKind = haste != null ? "equip_visible" : null;
                }
                String pump = firstVisible(plan.payoffCards("mass_pump"), view);
                predicates.put("haste_source", haste);
                predicates.put("haste_kind", hasteKind);
                predicates.put("mass_pump", pump);
                predicates.put("own_board_power", view.ownBoardPower());
                predicates.put("table_life", tableLife);
                if (haste == null) {
                    return "haste_source_not_visible";
                }
                // v1 alpha approximation: raw board power, or a visible mass
                // pump backed by the (infinite) pool — Finale/Craterhoof class
                if (pump == null && view.ownBoardPower() < tableLife) {
                    return "projected_alpha_below_table_life";
                }
                return null;
            }
            case "COMMANDER_DMG_SEQUENCE": {
                String commander = plan.payoffCards("commander_creature").stream()
                        .filter(c -> view.locate(c) == SeatView.Presence.BATTLEFIELD)
                        .findFirst().orElse(null);
                predicates.put("commander_on_battlefield", commander);
                predicates.put("note", "slowest route: one opponent per combat, survives table cycles");
                return commander != null ? null : "commander_not_on_battlefield";
            }
            default:
                return "no_v1_predicate";
        }
    }

    /** First card visible to the seat (battlefield/hand/command), else null. */
    private static String firstVisible(List<String> cards, SeatView view) {
        for (String card : cards) {
            SeatView.Presence where = view.locate(card);
            if (where == SeatView.Presence.BATTLEFIELD || where == SeatView.Presence.HAND
                    || where == SeatView.Presence.COMMAND) {
                return card;
            }
        }
        return null;
    }

    /** First card in exactly the given zone, else null (PR-25 haste v2). */
    private static String firstIn(List<String> cards, SeatView view, SeatView.Presence zone) {
        for (String card : cards) {
            if (view.locate(card) == zone) {
                return card;
            }
        }
        return null;
    }

    private static ArenaEvent event(String type, SeatView view, String route,
            Map<String, Object> predicates, String failedPredicate) {
        ArenaEvent event = ArenaEvent.of(type, view.turn(), view.seatIndex()).with("route", route);
        if (failedPredicate != null) {
            event.with("failed_predicate", failedPredicate);
        }
        Map<String, Object> values = new LinkedHashMap<>();
        predicates.forEach((k, v) -> values.put(k, v == null ? "absent" : v));
        return event.with("predicates", values);
    }
}
