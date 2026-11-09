# Earlier supplementary material

These sections come from the supplement of earlier versions of the paper. The
current paper does not use them, and the current supplement
(`paper/supplement.tex`, built into `output/pdf/` under its title) does not
depend on them. They are kept unchanged, with their original section numbers,
because the code and data they describe are still in the repository: the
finite-capture ambiguity proof and its executable example, the unbounded
obstruction order, the complete-log verifier, the conditional two-state
calculation, a verified MDN source-file return, the study contract and
controlled HTTP execution of earlier rounds, the label-alphabet synthesis
results, and a six-page natural source-revision audit. Cross-references to
sections not listed here point to the earlier supplement; their content now
lives in the current supplement.

## S1. Precise evidence semantics

A resource key consists of a stable resource identifier plus every request-context component that can change the selected representation. A representation is an exact byte value in this model. Different encodings or personalization contexts are separate histories unless an explicitly declared equivalence relation is substituted. Such a substitution changes the target of the theorem.

Fix a nondegenerate bounded real interval W and finitely many resources. Histories are right-continuous piecewise-constant functions with finitely many changes. Each resource's alphabet contains its target x_i and at least one non-target value. Point observations are exact and internally consistent: two observations of the same resource at the same time cannot disagree.

Capture records and complete change logs are different evidence types. A capture records one value at one time. A complete log records all change events, the state at the beginning of W, and coverage through W's end. Neither two equal hashes nor a large sample establishes log completeness. Cryptographic hashes are used as an engineering representation of exact byte identity; collision resistance is a separate implementation assumption and is not responsible for the return phenomenon.

## S2. Full proof of finite-capture ambiguity

Let distinct observation times be t_1,...,t_q. Assume there is no t_j at which every resource is observed with its target value.

For each t_j construct a state vector s_j. Set every observed component to its recorded value. If any recorded component differs from its target, assign the unobserved components arbitrarily. If all recorded components are targets, at least one component is unobserved; assign that component a non-target value. Thus s_j respects all observations at t_j and is not the all-target vector.

Choose disjoint half-open neighborhoods of these finitely many times, clipped at the window boundary when needed. Make the history constant and equal to s_j on each corresponding neighborhood. On the rest of W, use a fixed state vector with at least one non-target component. Boundaries can be assigned to the segment beginning there, preserving right continuity. There are finitely many boundaries, every observation is satisfied, and the all-target tuple never occurs. Call this history H−.

Because a finite set of points cannot exhaust a nondegenerate real interval, choose an open interval J within W containing no observed time. Replace H− on a smaller half-open subinterval of J by the all-target tuple. The resulting H+ remains piecewise constant with finitely many changes, preserves every observation, and has a nonempty coexistence interval. This proves the proposition.

The result also covers an adaptively chosen finite observation schedule after the fact: both constructed histories give the same answers along that observed execution. It is not a lower bound against systems with change notifications, continuous observation, known minimum dwell times, no-return promises, or cooperative snapshot protocols. A single simultaneous complete all-target observation is itself a positive existence witness. Finite observations alone cannot refute existence somewhere in W because a short unobserved coexistence episode can always be inserted.

## S3. Executable smallest example

Window: [0,4). Resource 1 is observed at t=0 and t=3 with value A. Resource 2 is observed at t=1 and t=2 with value B.

History H+: resource 1 is A throughout; resource 2 is B throughout.

History H−: resource 1 has A on [0,1), a on [1,3), and A on [3,4). Resource 2 has b on [0,1), B on [1,3), and b on [3,4). Lowercase letters name different byte values. Both histories satisfy all four records. In H−, V_1=[0,1) union [3,4), V_2=[1,3), and their intersection is empty. The half-open convention makes the switch at t=3 unambiguous; no instantaneous coexistence is accidentally introduced.

The fixture is returned by `sparse_ambiguity_fixture`. Its test checks the observed values against each full history and then verifies opposite coexistence outcomes.

## S4. Sufficient continuity and epoch guarantees

If V_i is an interval and both a_i,b_i belong to it, every point between the two belongs to it. Thus max_i a_i ≤ min_i b_i supplies a common witness t. This proof uses a property of the true history, not an inference that the history is an interval because two observations agree.

A service can instead expose a token allocated anew whenever the relevant representation changes, including a change back to previously served bytes. Tokens must not be reused during the certification horizon, and a token/value pair must be read atomically. If the same token is returned at a_i and b_i, no relevant change can have occurred between them: any change would have advanced to a fresh token. The previous argument then applies.

This is a condition on the token observed at the current resource key. Uniquely identifying an immutable stored version is insufficient if the service can later select that version as current again. Section S19 distinguishes version allocation from current-key activation and audits the actual request selector.

An opaque ETag can be generated by hashing bytes and therefore does not imply this contract. A revision number in a source repository also does not certify a deployment unless the serving system binds each response to that revision and all relevant updates are accounted for. On multiple origins, clock uncertainty must be handled before comparing a_i and b_i. The complete-log sweep assumes a common exact time axis; the request-window helper added in this revision accepts conservative read bounds after the caller has performed any necessary clock conversion.

## S5. Unbounded obstruction order

For m≥2 set W=[0,m). For each i in {0,...,m−1}, let V_i=[0,i) union [i+1,m), omitting empty pieces. Every V_i has at most two intervals. The complements [i,i+1) partition W, so no time is in all V_i. Remove any V_j. Every time in [j,j+1) now belongs to all remaining sets. Consequently every proper subfamily has nonempty intersection, and the complete family is an inclusion-minimal conflict of size m.

For any fixed test arity k, taking m=k+1 defeats all tests involving at most k resources. This is the classical failure of a finite Helly number for unions of two intervals. The claim here is its consequence for validating returned content values; the construction is not claimed as a new result in combinatorial geometry.

## S6. Global decision and certificates

Normalize each resource's intervals by sorting and merging overlap or adjacency. This step prevents one resource from being counted twice. Clip every interval to W. A beginning contributes +1 and an end contributes −1. Aggregate all deltas at a boundary before processing the segment that begins there. The active count on an elementary segment equals the number of resources whose target is present on that segment, because no resource can change validity inside it. Emit exactly those segments whose count equals n and merge adjacent emitted segments. This proves soundness and completeness. Sorting and normalization take O(M log M + n) time; event storage is O(M), where M counts supplied intervals and n counts resources, including empty validity sets.

For an empty intersection, choose an absent resource on every elementary segment. The certificate contains contiguous covering triples (start, stop, resource). The independent checker validates:

1. The first segment starts at the beginning of W, each segment begins where the previous one ends, and the last ends at the end of W.
2. Every segment has positive length and a valid resource index.
3. The chosen resource's validity set has no positive-length intersection with the claimed segment.

Under half-open integer-endpoint semantics this suffices for coverage of every time in W. No segment can contain a time where all targets are present, and the segments cover W. The reference builder maintains one monotone interval cursor per resource. Every elementary segment inspects at most n resources, while all cursors together advance at most M times. Its total bound is O(M log M + Mn + n), including preprocessing. The project does not conflate that bound with the decision algorithm's O(M log M + n) bound.

The optional conflict extractor iterates over resources and permanently removes one whenever the remaining family still has empty intersection. A resource retained earlier cannot become removable later: deleting additional constraints only enlarges an intersection. Therefore the final family is inclusion-minimal. The algorithm does not solve the minimum-cardinality problem.

## S7. Conditional two-state calculation

Let X be a two-state continuous-time Markov chain with rate λ in both directions. Its transition probabilities are P_AA(s)=(1+exp(−2λs))/2 and P_AB(s)=(1−exp(−2λs))/2. By the Markov property,

P(X(t)=B | X(0)=A, X(T)=A) = P_AB(t) P_BA(T−t) / P_AA(T).

Substitution yields the expression implemented in `src/temporal.py`; this auxiliary process model is not a result claimed by the revised main paper. At t=0 or t=T the probability is zero. At λ=0 it is zero everywhere. At t=T/2 and λT tending to infinity it tends to one half. These are checks on an illustrative process model, not assumptions needed for the deterministic impossibility statement. The implementation uses `expm1` for stable evaluation near zero.

## S8. Reproduction and exact counts

From the project root run:

```
python3 -m unittest discover -s tests -p 'test_temporal.py' -v
```

No third-party packages or network access are needed for these checks. The executed suite has nine tests:

- For three resources and four time cells, every resource has 2^4=16 target-presence masks, giving 16^3=4096 cases. Interval-sweep output is compared against bitwise conjunction, an oracle that does not reuse the sweep. Certificates are checked for every empty case.
- Ten nonempty half-open intervals have endpoints in {0,1,2,3,4}; all 10^3=1000 ordered triples are checked for the pairwise implication.
- For every m=2,...,12, the obstruction has empty full intersection, every m−1 subfamily intersects, and deletion returns all m resources.
- Other tests cover duplicated and overlapping intervals, coincident boundaries, out-of-window data, an empty family, invalid revision ordering, a missing initial boundary, the ambiguous transcript, bad certificates, and the Markov expression's basic limits. A non-integer certificate resource index is rejected before indexing; every revision timestamp is checked, including non-target and out-of-window revisions.

All nine tests passed in the executed run. Runtime is not reported as a benchmark. The test counts describe constructed mathematical instances, never real pages. General claims rely on proofs rather than extrapolating these bounded enumerations.

## S9. A verified MDN source-file return

On 4 November 2026 we collected three source snapshots from the public `mdn/content` repository. The selected path is `files/en-us/web/css/reference/selectors/_colon_fullscreen/index.md`. These are consecutive states in the returned history for this file, not adjacent commits in the whole repository.

| State | Commit prefix | Commit timestamp (UTC) | UTF-8 bytes |
|---|---|---|---:|
| A | c52ed787 | 2025-11-03 17:48:17 | 2874 |
| B | a87a4b68 | 2025-11-17 08:26:40 | 2826 |
| A2 | 21da3683 | 2025-11-18 10:27:46 | 2874 |

The immutable source references are:

- [A: original source](https://github.com/mdn/content/blob/c52ed787442db9d65b21f5c2874fa6bfd08a253a/files/en-us/web/css/reference/selectors/_colon_fullscreen/index.md).
- [B: changed source](https://github.com/mdn/content/blob/a87a4b68c623831278275f17c2c4cde185c09241/files/en-us/web/css/reference/selectors/_colon_fullscreen/index.md).
- [A2: restored source](https://github.com/mdn/content/blob/21da3683d67c91c9a75a1c3fe98d406c82d8bf8b/files/en-us/web/css/reference/selectors/_colon_fullscreen/index.md).
- [The restoring commit](https://github.com/mdn/content/commit/21da3683d67c91c9a75a1c3fe98d406c82d8bf8b) explicitly identifies the changed commit it reverts.

The intermediate edit replaces a Markdown link for the `background-color` property with a `cssxref` macro. The final snapshot restores the entire earlier byte string. A and A2 have Git blob SHA-1 `300cb052298f9b3c2c7f58b6ca82c1325bb7c311`; B has `708410fafc3e1308f48e2bf103e2c7afbfc3959b`. These are Git object identifiers, not a recommendation to use SHA-1 for adversarial integrity protection.

The raw UTF-8 strings and provenance metadata are in `data/raw/aba-source.json`. Running the following command requires only the Python standard library and no network:

```
python3 scripts/verify_aba.py --output data/processed/aba-verification.json
```

The verifier reconstructs each Git blob as `b"blob " + decimal_byte_length + b"\0" + file_bytes`, checks its SHA-1 against the recorded object identifier, also computes SHA-256, compares the full bytes, and checks the recorded timestamp and file-history ordering. The archived result confirms all three object hashes, A=A2, and A≠B. Source text is preserved unmodified and attributed to MDN contributors. The source license, including the distinction between prose and examples, is archived in `data/raw/mdn-LICENSE.md`; the prose license is CC-BY-SA 2.5.

Selection was purposive: public commit searches for revert operations were followed by inspection of a documentation rollback and its affected file. No random sampling of MDN or the Web was performed. The 17 attempted network reads described in the collection note are acquisition operations, not 17 independent observations of the phenomenon.

The evidence supports exactly one empirical proposition: a real Web-document source history can change and return to identical bytes, so endpoint equality does not establish an unchanged source history. Commit timestamps are not deployment timestamps. The macro rewrite may preserve rendered meaning; no semantic contradiction is claimed. This single-resource example is not evidence of a multi-resource coexistence failure, a population failure rate, or deployment of the proposed epoch contract.

## S10. Empirical study contract

An empirical extension must keep byte identity, revision identity, and deployment time separate. For Wiki raw source, retrieve complete revision metadata with ids, timestamps and sha1, paginate until the fixed window is exhausted, include the revision preceding the window, and record hidden or unavailable revisions as unknown. The page's raw source does not specify template-rendered HTML. For Git-backed documentation, verify equal blobs at endpoints and an intervening unequal blob, but label the result a source-history demonstration until deployment logs are obtained.

Before executing a prevalence study, freeze the resource-selection rule, time window, reading schedule, missing-data rules and denominators. Report total pages, revisions, complete histories, endpoint-equal pairs, true returns among those pairs, and the duration distribution of unseen changes. Cluster uncertainty by resource if estimating across pages. Preserve all raw responses, provenance URLs, response digests, selected target values and generated interval tables. Do not select only reverting pages and present their error rate as representative of the Web.

The core study combines controlled executions on three HTTP stacks, finite-contract characterization, and exact label synthesis with independent certificates. This does not establish natural production incidence or make the underlying snapshot, reachability, poset, or coloring principles new.

## S11. Controlled HTTP execution

The loopback service in scripts/run_http_demo.py executes the smallest example through actual HTTP GET requests. It binds only 127.0.0.1. A lock binds each returned body to its SHA-256 ETag and per-resource change epoch. Transitions occur between requests at explicitly recorded logical ticks; this is not a wall-clock race experiment. Both resources have equal endpoint ETags. Resource a has epochs 0 and 2, while resource b has epoch 1 at both observations. Complete transition logs yield V_a=[0,1) union [3,4) and V_b=[1,3), hence no coexistence.

All four requests returned HTTP 200 in the recorded run. Response bodies, headers, transitions, and exact derived intervals are in data/derived/http_demo.json. Running the script regenerates this trace and asserts the expected conditions. The result shows the semantic distinction at a real HTTP interface; it does not estimate natural recurrence frequency or demonstrate a defect in a particular archive deployment.

## S16. Consistency of the delivered claims

The central audit applies the finite-contract criterion to a declared graph and endpoint scope. Sections S17–S18 retain the all-state synthesis results. Finite-capture ambiguity, the Helly obstruction, and the conditional Markov calculation remain auxiliary material. The complete-log checker certifies only the supplied history; the contract checker certifies only G and R; synthesis certificates concern the specified all-state body graph and available fields; HTTP traces certify controlled schedules; source records certify source returns. Official service documentation and the SDK request fixture in S19 supply different, explicitly bounded evidence.

The underlying safety, poset, and coloring methods are established. The specialized results concern the endpoint-continuity predicate and the information available to compute a label. Neither the constructed models nor the controlled executions measure natural deployment incidence or errors by a deployed archival consumer.

## S17. Exact synthesis with distinguishable states

Fix a nonempty finite graph G=(V,E) and faithful body map b:V→B. **This synthesis theorem assumes R=V**: every state is a certifiable read state, every finite path is allowed, and states may have positive residence. An auxiliary label f is safe if every path with equal endpoint pairs (b,f) has the same body at every state. A strong body-binding label must also satisfy f(s)=f(t) ⇒ b(s)=b(t). The strong condition distinguishes different representation bodies; it does not by itself implement all HTTP requirements. The endpoint-scoped audit in S12 does not establish these alphabet formulas for partial R.

Full-state synthesis assumes that f may be computed as a function of the actual supplied state. Therefore the labeling implementation must be able to distinguish every node. A model that gives different names to two indistinguishable visits has not supplied the missing memory. The solver adds no history variable. A durable counter, a new boot identity, or a history observer changes this input model.

### Existence and minimum alphabet

A fixed-state continuity label exists if and only if every strongly connected component is monochromatic. If the condition holds, condense G into a DAG D. For a body c, say that C precedes D when components C,D have body c and a C-to-D path visits another body. This relation is a strict partial order. Let Hc denote its height. The exact minimum auxiliary alphabet is max_c Hc; the exact minimum strong body-binding alphabet is sum_c Hc.

To prove necessity, choose differently bodied states s,t in a mixed SCC. Paths s→t and t→s concatenate to a body-changing closed walk. The first and last state are the very same s, so every fixed function f repeats its label. No label alphabet, finite or infinite, removes this fixed-state obstruction.

Now suppose all SCCs are monochromatic. The condensation DAG cannot have a path from a component back to itself, so this return relation is irreflexive. Concatenating witnesses proves transitivity. Between any chosen states of two comparable components, internal SCC paths can be joined to the body-changing witness. Consequently their entire label palettes must be disjoint. A maximum chain of length Hc forces at least Hc labels, even if labels are not constant within each SCC.

For the upper bound assign each component the length of the longest chain in this return order ending there, for its own body c, and assign this rank to all its states. Comparable components have strictly increasing ranks. Every path that leaves and returns to a body has comparable endpoint components, so it cannot have equal endpoint ranks. The assignment is safe. This is the standard rank/antichain construction associated with Mirsky's height decomposition, not a new poset theorem. Auxiliary rank values can be shared between different bodies, so the overall count is the maximum Hc. Strong binding requires disjoint palettes for different bodies; shifting each body's ranks into disjoint integer ranges attains the sum lower bound.

### Computing ranks and their lower-bound witnesses

For each body c, process components in topological order. The score at a component is the maximum number of c-runs on any path ending there. It starts at one at a c-component and zero elsewhere. Following an edge into c from another body increases the predecessor's score by one; other edges preserve it. The maximum score at a c-component is its partial-order rank. A predecessor achieving the score supplies a path whose c-runs give an attaining chain. Adjacent chosen chain components have explicit paths through another body in the original graph.

The reference implementation uses BFS from every original state to build reachability, then SCCs and the condensation, followed by the topological recurrence. This simple implementation uses O(|V|(|V|+|E|)) reachability work, O(|B|(|V|+|E|)) rank work, and O(|V|²+|E|) stored reachability/edges. The total number of chain links is bounded by |V|; reconstructing their paths adds at most O(|V|(|V|+|E|)). The implementation is not presented as a new optimized graph algorithm.

A lower-bound checker validates each chain's body and distinct states, every witnessing edge, and each intermediate different body. A separate upper-bound checker validates that every and only graph state has a label, the actual number of distinct labels equals the reported bound, different bodies have different strong labels, and the original continuity audit accepts the assignment with a valid invariant. Thus optimum is established by an attained lower bound and an independently checked upper bound, rather than trusting reported ranks or counts.

## S18. Exact synthesis from existing fields

Continue to assume R=V and fidelity on every state. Let h:V→Y describe all fields available to the label implementation. Require f=g∘h for a deterministic g. Every state in one h-fiber must receive the same label. This is a constraint on information, not on spelling or numerical encoding of the token. In particular, the SCC and coloring claims must not be applied to a service model by silently removing uncertifiable error states.

Construct an undirected graph Qh on distinct field values. Whenever an original path starts and ends with the same body but visits another body, insert the edge between its endpoint h values, retaining self-loops. For strong body-binding labels, also connect h(s),h(t) for every pair with different bodies, even when no path connects them. A loop proves infeasibility. If there is no loop, the exact minimum alphabet is the chromatic number χ(Qh).

Every edge represents a necessary inequality between its labels, so every safe g is a proper coloring. A loop requires g(y)≠g(y) and rules out all g. Conversely, an unsafe return under a proper coloring would have induced an edge whose endpoints received the same color, a contradiction. The additional cross-body edges enforce precisely the strong-binding condition. This also explains why an observable fiber containing different bodies can be feasible for an auxiliary label but infeasible for a strong one.

### Decision complexity and the visibility gap

The decision problem takes G,b,h and an integer K and asks whether a safe auxiliary label with at most K values exists. It is in NP: an assignment to field values is a polynomial-size certificate and can be checked for fiber consistency and graph continuity in polynomial time. K can be bounded by |Y| whenever the conflict graph is loop-free.

For NP-hardness, take an arbitrary undirected graph H with at least one edge. For each edge {u,v}, create a separate three-state A→B→A path. Assign endpoint fields u and v and assign every middle state the same separator field. Add an isolated A state for every vertex so isolated vertices are not lost. Different path components have no transitions between them. Thus each path contributes exactly the auxiliary conflict u–v, and the separator has no auxiliary conflicts. The projected conflict graph is H plus an isolated vertex, so its chromatic number equals χ(H). Taking K=3 reduces 3-colorability. The original body graph uses only two bodies and has depth two. Therefore this decision problem is NP-complete on that restricted family, and minimizing the alphabet is NP-hard.

The full-state auxiliary optimum of every such nonempty-edge construction is two: first and last A states must differ but different edge components can reuse their two ranks. In contrast, choose H to be a complete graph on arbitrarily many vertices and the field-restricted optimum grows without bound. Thus restricting observability can impose an arbitrarily large label-alphabet cost, not only computational hardness. This is an alphabet comparison on fixed models, not a lower bound on the persistent memory of a general concurrent protocol. For strong labels in this reduction the optima are three and χ(H)+1, respectively.

### Independent exact-coloring certificate

`synthesize_observable_validators` computes the conflict graph and uses exact saturation-order backtracking to obtain a coloring. It then independently enumerates fixed-order color prefixes for one fewer color. Colors are canonicalized by their first occurrence: the next state can use a previously introduced color or the next new one, up to the proposed budget. Every complete coloring can be renamed into this canonical form.

An unsatisfiability proof node contains every canonical candidate branch. A branch either names a previously colored adjacent vertex with the same color, blocking that choice, or contains the complete proof for the extended prefix. The separate `verify_coloring_lower_bound` checks the branching count, each blocker, and every child. Reaching a complete valid coloring makes a purported lower-bound proof fail. Consequently an accepted proof excludes every coloring using one fewer label. No maximum-clique computation is used as a substitute for chromatic number.

Every conflict also has evidence in the original graph: a body-return path, or a two-state different-body pair for strong binding. The checker verifies that evidence and its projected endpoints. It only needs the listed conflicts to be sound for a lower bound. Independently auditing the proposed assignment on the original graph supplies the upper bound and catches an unsafe assignment even if the conflict generator omitted an edge. The verifier additionally checks all state/field domains, equality within every h-fiber, exact distinct-label counts, and strong binding when requested.

Exact search defaults to at most 12 observable values and one million lower-proof nodes. Exceeding a limit aborts rather than reporting an unproved optimum. A loop can be certified before the coloring limit. These are reproducibility limits of this small reference implementation, not theoretical tractability bounds.

### Inputs, results, and independent oracles

Run from the project root:

```
python3 -m unittest tests.test_validator_synthesis -v
python3 scripts/run_validator_synthesis.py
```

Inputs are `data/constructed/contracts.json` and `data/constructed/validator-projections.json`. The output `data/derived/validator-synthesis.json` records both input hashes, exact assignments, chain paths, conflict paths, exhaustive coloring-prefix proofs, and independently checked safety results.

The full-state oracle exhausts 512 directed graphs on three named nodes with all 8 binary body maps (4,096 cases), plus 64 ordered DAGs on four nodes with all 16 binary body maps (1,024 cases). The available-fields oracle covers the 512 three-node graphs, 8 body maps, all 5 partitions of their states into observable fibers, and auxiliary/strong semantics: 40,960 cases. It independently computes all-pairs reachability with Floyd–Warshall and directly enumerates assignments against state-pair constraints. It does not consume the synthesizer's conflict graph, SCCs, or rank values. Every exact count and infeasibility result agrees.

The suite has ten test methods. Additional tests reject missing states, a reported label count smaller than the actual assignment, cross-body reuse of a strong label, unsafe returns, omitted conflict witnesses, and incomplete lower-bound trees. A five-cycle gadget is specifically included because its auxiliary chromatic number is three but its maximum clique size is only two. The original state graph needs two auxiliary labels. The strong-label counts are four and three, respectively.

For the thirteen mechanism models, three read-fidelity failures are ineligible for label-only repair. Among the remaining ten, six allow full-state labels and four have mixed-body SCC obstructions. Restricting h to (body, existing validator) gives four feasible cases, matching the original auditor as it must: a deterministic remapping cannot distinguish equal old pairs. The two full-state-feasible but field-infeasible cases are reset and reused-boot identity. This is a consistency demonstration of the information constraint, not a measured production repair rate. Four separate declared examples cover hidden rollback, branch reuse, a field merging different bodies, and the five-cycle reduction.

### Relation to existing theory

ABA-detecting registers with reader-specific operations and shared state are studied by [Aghazadeh and Woelfel, PODC 2015](https://arxiv.org/abs/1507.02722). [Ellen et al., STACS 2019](https://doi.org/10.4230/LIPIcs.STACS.2019.26) explicitly discuss double collects whose returned vector never coexisted. These are predecessors of the motivating phenomenon, but their protocol state and operations are not fixed-state labeling functions.

[O'Kane and Shell, ICRA 2015](https://jokane.net/pubs/OKaShe15.pdf) synthesize state-dependent outputs whose complete sequences enable selected state distinctions. [Saberifar et al., IJRR 2019](https://doi.org/10.1177/0278364918801503), Section 5.2, give observation-map minimization hardness through edge gadgets and chromatic-number correspondence. Neither generic state-label synthesis nor observation-compression/coloring hardness is new here. The specialization is the body-return relation induced by endpoint continuity, its partial-order structure with full state, and its projected conflict characterization under fixed fields. Mirsky's decomposition is the established rank/antichain ingredient. The certificates keep this specialization executable without adding an unmodeled history variable.

## S20. Natural source-revision audit (six purposive pages)

A second source study fixes six English Wikipedia titles: World Wide Web, HTTP,
HTML, CSS, JavaScript, and Web browser. The queried interval is 2024-01-01T00:00:00Z
through 2025-01-01T00:00:00Z, in ascending revision order. The set is purposive;
World Wide Web was explored before the other five titles were fixed. There is
no random-sampling or preregistration claim. The exact responses and acquisition
record are in data/raw/revision-histories-2024. No user names or edit comments
were requested.

The offline audit defines one return for consecutive appearances of the same
content hash with at least one differing intermediate revision. Adjacent
unchanged revisions are not returns. Every detected return retains endpoint and
intermediate revision IDs. This definition avoids counting all quadratic pairs
inside one repeated-content sequence as separate events.

| Page | Revisions | Content runs | Hash returns | Maximum episodes of one content hash |
|---|---:|---:|---:|---:|
| World Wide Web | 53 | 53 | 1 | 2 |
| HTTP | 186 | 185 | 70 | 15 |
| HTML | 50 | 50 | 3 | 2 |
| CSS | 127 | 126 | 43 | 8 |
| JavaScript | 133 | 133 | 5 | 2 |
| Web browser | 85 | 85 | 9 | 3 |

There are 634 recorded revisions and 131 hash-return events. The first return
on each page is selected mechanically. A further API request retrieves all 18
source revisions. The audit checks their page/revision identities, timestamps,
parent links and hashes against the metadata response; computes the content
hash from the decoded UTF-8 source; and directly compares endpoint bytes while
requiring the intermediate bytes to differ. Thus six selected returns are
byte-verified. The 131 total is a metadata result, not 131 independent byte
comparisons. All source texts, revision links, and CC BY-SA 4.0 attribution are
frozen with the data.

All adjacent recorded revisions have matching parent links, all revision IDs
are distinct, and the supplied lists have no tied timestamps. These checks do
not certify the absence of historical deletion or suppression. They do not turn
source-revision timestamps into exact HTTP serving or rendered-page validity
intervals. Transcluded templates, media, caches, and deployment are outside the
source-text object studied here. The evidence establishes actual source-content
return in a selected public collection, not a Web failure rate or a production
consumer's mistaken decision.

The declared-path label bounds are also recorded. For each individual sequence,
the minimum auxiliary alphabet is the largest number of episodes of one content
hash; the minimum strong alphabet is its number of content runs. Those are
applications of the proved path case, not an operational minimum for Wikipedia.
The API's already distinct revision IDs show how this collection distinguishes
events that content identity merges. No change to Wikipedia is proposed or
needed to separate these recorded source revisions.

Offline reproduction:

```sh
python3 scripts/run_revision_audit.py
python3 -m unittest discover -s tests -p 'test_revision*.py' -v
```

The collector is kept separate from the audit. Recollection needs network
access and an informative client identifier; it creates a new directory rather
than overwriting the frozen evidence. Missing or inconsistent provenance is an
error, not silently accepted as a zero-return observation.

## S21. Alphabet size and accepted endpoint pairs

The optimum in S17 concerns the number of labels in a fixed-state equality certificate. It does not optimize the accepted safe endpoint pairs or the memory of a history-dependent observer. A rank is a maximum of path scores and may change even along a body-preserving edge.

For an explicit example let s,u,v have body A and z have body B, with exactly four edges: s to u, u to v, s to z, and z to v. Every s-to-u path and every u-to-v path preserves A. The s-to-z-to-v path does not. An equality certificate accepting both first pairs forces equal labels at s and v, which is unsafe. Thus no fixed-state equality assignment, of any alphabet size, accepts both safe pairs.

The minimum auxiliary and strong alphabets are respectively two and three. The rank assignment gives s,u label 1 and v label 2, rejecting the safe u-to-v pair; an equally small alternative groups u,v instead. Neither partition contains the other in accepted-pair inclusion. Both accept one of the two safe nontrivial pairs; this example does not show inferior unweighted coverage of the rank assignment within the equality class.

A general endpoint-pair predicate can accept both using ordinary reachability, provided its observations retain the necessary distinctions. Require a compatible path between the endpoint observation fibers; then all nodes in the intersection of forward reachability from the first fiber and backward reachability from the second must have the target body. Incompatible pairs report model/evidence incompatibility rather than a vacuous continuity guarantee. This scope observation is not a new synthesis theorem or a production benchmark.

`scripts/check_label_objective.py` independently enumerates all ten paths, including zero-edge paths, and all fifteen canonical partitions. It checks ten safe auxiliary and three safe strong assignments, all sixteen ordered endpoint pairs, and the existing full-state and field-restricted certificate verifiers. The complete outputs and implementation hashes are in `data/derived/label-objective-audit.json`. Run `python3 scripts/check_label_objective.py` to print the exact JSON. All inputs are defined in that script; no external data or network is required.
