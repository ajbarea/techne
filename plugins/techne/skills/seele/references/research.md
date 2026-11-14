# What each rule rests on

SEELE's protocol is a list of answers to measured failures of model judges. This page gives the source for each rule and says what the script does about it. Where a source supports less than the rule, the page says so.

## The shape: opinions, blind review, a chair

Three stages (independent answers, anonymous peer ranking, one model that writes the final answer) is the shape of Karpathy's [llm-council](https://github.com/karpathy/llm-council). SEELE keeps the stages and changes what each one hides, counts and reports.

A panel is worth its cost only when its judges differ. Verga et al. ([arXiv:2404.18796](https://arxiv.org/abs/2404.18796)) found that a panel of smaller models from different families agreed with human judgments better than one large judge, at a fraction of the cost, and that a single judge's bias toward its own family mostly disappears in the panel.

## Round 1: no candidate list

Kapetanovic et al. ([arXiv:2608.25869](https://arxiv.org/abs/2608.25869)) show that a judge shown an earlier score moves toward it. A list of options is the same kind of anchor: a seat handed three titles improves one of them instead of writing the fourth. So round 1 hands every seat the same brief and no candidates, and the user's own candidates join the pool only afterwards (`pool --add`).

## Round 2: what a ballot hides

| Rule | Source | What the script does |
|---|---|---|
| Order differs for each judge | Zheng et al., NeurIPS 2023 ([arXiv:2306.05685](https://arxiv.org/abs/2306.05685)) name position bias in model judges. Wang et al. ([arXiv:2305.17926](https://arxiv.org/abs/2305.17926)) reversed a ranking of two systems by changing only the order of the answers. Shi et al. ([arXiv:2406.07791](https://arxiv.org/abs/2406.07791)) found the bias strongest when the answers are close in quality, which is the usual case for a panel's pooled candidates. | `pool` writes each ballot in its own order |
| The orders are balanced, not just shuffled | Wang et al. correct the bias by scoring each pair in both orders; Tang et al., NAACL 2024 ([arXiv:2310.07712](https://arxiv.org/abs/2310.07712)) do it for rankings by aggregating over shuffled orders. Independent shuffles balance positions only on average, and a panel has few judges. | The orders are rows of a Williams design (Williams 1949, [doi:10.1071/CH9490149](https://doi.org/10.1071/CH9490149)): no candidate holds the same position on two ballots while there are at least as many candidates as judges. With an even number of candidates and as many judges, each candidate also follows every other candidate exactly once. Outside those cases the balance is approximate. |
| Each ballot has its own labels | Zheng et al., ICLR 2024 ([arXiv:2309.03882](https://arxiv.org/abs/2309.03882)) show models prefer certain option letters, apart from position. | A ballot labels its candidates with random codes such as `K7`, drawn per seat, never one that appears in the brief. The script translates them back when it counts. |
| No pitches on the ballot | Zheng et al. (2023) name verbosity bias: longer answers win. A proposer's reasoning is also a fingerprint of its author. | The ballot shows each candidate's text only. The reasons go to the chair. |
| No authors on the ballot | Panickssery et al., NeurIPS 2024 ([arXiv:2404.13076](https://arxiv.org/abs/2404.13076)) found that models recognise their own text and that the ones that recognise it best favour it most. | Authors, seat numbers and model names never appear on a ballot. A ballot sits in a folder of its own, apart from the seat's round 1 answer. |
| Reasons before the ranking | Wang et al. found that asking for the evidence before the score makes the score more stable. | The ballot asks for a one-line assessment of every candidate, then the ranking. |

## The count

- **A recount without each author's own ballot.** Wataoka et al. ([arXiv:2410.21819](https://arxiv.org/abs/2410.21819)) trace self-preference to familiarity: a judge scores text highly when it finds the text unsurprising, whoever wrote it. Hiding the author therefore does not remove the bias. The vote table has a column that leaves out each candidate's own author, and the report flags a lead that changes on that count.
- **Points, first choices and head-to-head together.** Zhao et al., EMNLP 2024 ([aclanthology 2024.emnlp-main.158](https://aclanthology.org/2024.emnlp-main.158/)) surveyed 52 multi-agent systems and found heavy reliance on a single deciding agent or on plurality voting; on their three benchmarks some ranked voting methods reasoned better and survived one failing agent. No single rule is right for every case, so SEELE counts Borda points for the headline and flags the cases where another rule disagrees: a leader that loses head to head, a tie, a candidate most seats rejected.
- **Agreement is reported, and so is how little it can mean.** Kohli ([arXiv:2605.29800](https://arxiv.org/abs/2605.29800)) measured nine judges from seven families and found their errors so correlated that the panel carried about two independent votes. The report prints Kendall's W for agreement and says when every seat is from one family. A unanimous panel of similar models is weaker evidence than its count suggests. The labels the script puts on W ("ranked alike", "partial agreement", "little shared order") are its own reading aids, not thresholds from a paper.

## No debate rounds

Choi et al., NeurIPS 2025 ([arXiv:2508.17536](https://arxiv.org/abs/2508.17536)) found that majority voting alone accounts for most of the gain attributed to multi-agent debate. Smit et al. ([arXiv:2311.17371](https://arxiv.org/abs/2311.17371)) found debate no more reliable than simpler ensembling and sensitive to its settings. Showing seats each other's answers also reintroduces the anchoring that round 1 removes. SEELE's seats never see each other; they meet only as anonymous candidates on a ballot.

## The chair

A final judge that also competes is the self-preference case again, so the chair holds no seat: it proposes nothing and casts no vote. It rules from a docket with seats, models and authors removed, and it must pick one of the voted candidates. The docket's vote table also leaves out the recount without each author's ballot, because points less that average would tell the chair which ballots came from a candidate's authors. A repair to the wording goes on a separate line that the report marks as not voted on.

The sources above support the panel and the blind count. They do not settle whether a strong single judge should overrule a vote, and Kohli's result cuts against trusting the vote alone. SEELE therefore reports both: the vote table, the chair's pick, and a bold line when they differ, with the vote listed as the first dissent. The reader sees the disagreement instead of one side of it.

## Limits

- Seats have no tools. A panel judges what is in the brief and cannot check a fact.
- Self-preference is reduced, not removed. Read the "other seats" column.
- A panel of Claude models alone is one family. It is still more than one sample, and the report says what it is.
- The research measured these biases on benchmark tasks with known answers. Titles, names and design choices have no answer key, so the report shows its working instead of a confidence score.
