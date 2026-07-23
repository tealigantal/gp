# Retired Contracts

**These contracts are historical names only. They are not valid architecture alternatives. Do not restore them for compatibility. Do not create adapters for them. Do not cite them as the current production path. Git history is the only source for their old implementation.**

| Retired name | Former location | Former responsibility | Replacement | Removal reason | Forbidden restoration |
| --- | --- | --- | --- | --- | --- |
| AdvicePick | contracts package | candidate payload | CandidateDecision | untyped split authority | aliases or adapters |
| DayBook | book package | daily decision container | RecommendationPlan | daily and runtime meaning mixed | fallback read |
| BoardEntry | book package | display entry | RecommendationPublication | projection duplicated decisions | display selector |
| LiveSlotArtifact | book package | intraday record | RuntimeObservation | runtime duplicated daily scope | daily mutation |
| MarketBook | book package | mixed runtime product object | RecommendationPublication | multiple owners | product read path |
| AdviceRun | judgment package | conversation binding | publication_id | product identity ambiguous | session bridge |
| CanonicalPick | runtime package | projection candidate | CandidateDecision | duplicate model | conversion adapter |
| CanonicalRunArtifact | runtime package | response projection | RecommendationPublication | second decision representation | renderer source |
| StoredSnapshot | storage package | persistence record | canonical aggregates | opaque payload | deserializer |
| DecisionContextSnapshot.v1 | decision pipeline | decision transport | RecommendationPlan | untyped command flow | builder |
| RecommendationSnapshot.v1 | storage schema | product persistence | recommendation_publications | retired schema | reader or writer |
| MarketTimeContext | runtime package | target timing | ResolvedPlanTarget | mixed phase identity | timing alias |
| recommendation_snapshots | SQLite table | old payload records | recommendation_plans and recommendation_publications | opaque aggregate | table recreation |
| current_snapshot | SQLite pointer | old current pointer | current_publication | wrong product identity | pointer recreation |
| daybook_versions | SQLite table | daily container history | recommendation_plans | duplicate storage | table recreation |
| /api/book/current | HTTP route | old product read | /api/recommendation/current | retired vocabulary | route alias |
| retired time fields | models and schema | mixed target and runtime time | canonical time vocabulary | ambiguous identity | field aliases |
