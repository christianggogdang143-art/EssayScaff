# ADOPTION REGISTER — third-party research foundations

Every externally-grounded component in EssayScaff is recorded here with its
paper citation, license, pinned version, and what was adopted. The defense
panel can read this one file and see the entire chain.

## 1. AcaWriter rhetorical-move taxonomy (adopted: taxonomy + message patterns)

- **What:** AcaWriter, Academic Writing Analytics project, UTS Connected
  Intelligence Centre — https://github.com/uts-cic/acawriter
- **Paper:** Knight, S., Shibani, A., Abel, S., Gibson, A., Ryan, P.,
  Sutton, N., Wight, R., Lucas, C., Sándor, Á., Kitto, K., Liu, M.,
  Mogarkar, R. & Buckingham Shum, S. (2020). AcaWriter: A learning analytics
  tool for formative feedback on academic writing. *Journal of Writing
  Research*, 12(1), 141–186.
- **License:** Apache 2.0 (free for thesis use; attribution in code + docs).
- **Adopted:** the rhetorical-move vocabulary (claim, evidence, elaboration,
  contrast, organization, reflection) and feedback-message patterns, mapped in
  `services/rhetorical_moves.py` onto every rule and prompt. Detection code
  remains EssayScaff's own spaCy pipeline.
- **Deliberately NOT adopted:** the Athanor parser binary. Upstream retired
  AcaWriter on 13 March 2026 ("codebase is ageing… can no longer maintain
  its security"); the parser needs a Python 2.7-era C++/Java toolchain
  (`make`, g++, `ant`) plus Docker, none of which this project depends on.
  Evaluated and declined — recorded here so the decision is defensible.
- **Defense line:** "Our feedback follows AcaWriter's validated
  rhetorical-move framework; our detectors implement it transparently."
- **Status:** ADOPTED (taxonomy + patterns). Binary: DECLINED with reason.

## 2. (Reserved) TextDescriptives metrics layer

- Status: APPROVED, not yet implemented. See plan: Hansen et al. (2023),
  *Journal of Open Source Software* 8(84), 5153. Aarhus University authors.
- Components scoped: readability, descriptive_stats, dependency_distance,
  pos_proportions (no model change). Coherence deferred (needs
  `en_core_web_md` + test updates).

## 3. (Reserved) ERRANT grammar taxonomy

- Status: PROPOSED, not yet implemented. Bryant, Felice & Briscoe (2017),
  *ACL*. MIT license, `pip install errant`.
