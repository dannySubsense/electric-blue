# Frank's Verdict — DDR backlog (DDR-02 … DDR-06)

- **Reviewer:** Frank (senior QC, judgment gate)
- **Date:** 2026-06-14
- **Scope:** across-the-board read of DDR-02..06 + DDR-REVIEW.md, as PROPOSED design records.

**Verdict:** Sound enough to start. Build DDR-02 next — but **strip the async sub-protocol
out of DDR-02** until Groq Batch audio support is verified, and you remove the only real
foot-gun in the foundation.

---

## Gut reaction
A real backlog, not a wish list. Sequencing is right, decisions are flagged honestly, nobody
pretends the unknowns are known. Two things would page someone; one is load-bearing.

## The risks

1. **LOAD-BEARING — speculative abstraction in the base layer.** DDR-02 (built next) cements
   an async `submit/poll/fetch` sub-protocol into the foundation every backend inherits. The
   sole justification for the async half is DDR-03, whose entire lifecycle (§3) rests on an
   **unverified assumption that Groq Batch accepts audio transcription** (DDR-03 D6). DDR-02
   lists "premature abstraction" as a risk and then commits one. Failure mode: ship the seam,
   later find the one consumer that justified it doesn't exist as specced — wrong shape welded
   under everything.

2. **DDR-05 dependency hell (contained).** whisperx ↔ pyannote ↔ torch vs faster-whisper ↔
   torch. High probability, but isolated to its own sprint and already carries the Option-B
   escape hatch (pyannote-direct, drop whisperx). Not a foundation risk.

3. **DDR-03 ⇄ DDR-04 hook contract (C1/C2/C3, MED).** Fixable when built together. C3 in
   particular: `wall_sec = time.time() - t_start` across a ~24h batch boundary is a lie — it
   will ship and silently report garbage durations on batch transcripts.

4. **Two unflagged:**
   - DDR-04 changes `write_outputs()` to return a dict; DDR-03's drain also calls
     `write_outputs()`. Whichever lands second must adapt or it breaks.
   - `schema_version` is internally contradictory: DDR-02 says "stay additive, don't bump";
     DDR-05 proposes bumping to `2` **only when speakers are present**. A backend that emits
     different schema versions depending on the audio is consumer-confusion waiting to happen.
     Data-dependent schema versions are a smell. Pick one.

## The conditions

1. **Before DDR-02 is built:** verify Groq Batch audio (D6) by hand, **OR** cut `AsyncBackend`
   out of DDR-02. The sync `Backend` Protocol + registry + `Capabilities` + `schema_version` +
   API characterization tests all stand alone and need nothing from DDR-03. Add `AsyncBackend`
   in the DDR-03 sprint once Groq is confirmed. *Preferred — removes the only speculative thing
   in the foundation.*
2. **One `schema_version` policy in DDR-02, data-independent.** Additive-at-v1 (lean, matches
   DDR-02's stated intent) or always-v2 for diarized docs. Not "v2 sometimes."
3. **Resolve the 03/04 hook as one contract** when building the second; put
   `submitted_at`/`completed_at` in the payload so batch timing isn't fabricated.
4. **Verify the cheap external unknowns on paper now:** Groq batch audio (D6), PyPI name (D1),
   dry `pip install ".[local,diarize]"` torch-matrix smoke. ~1 hour; de-risks three sprints.
5. **Re-sequence to build on verified ground: 02 → 04 → 03 → 05 → 06.** DDR-04 is fully
   implementable today on the sync seam; DDR-03 is blocked behind an external unknown. Don't
   stall the queue behind Groq verification.

## What I am NOT worried about
- Format/consistency — clean (per DDR-REVIEW.md).
- The honestly-flagged project risks (Groq D6, whisperx matrix, PyPI name) — correctly marked
  VERIFY/DECISION, not asserted as settled. Good.
- Dependency cycles — none; the graph is sound.
