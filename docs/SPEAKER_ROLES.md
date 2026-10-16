# Caller/agent and customer attribution

New analyses no longer assume that the first speaker is the company agent. In the
existing API, **Caller** means the company's agent/representative, even on an incoming
call. Customer means the client/prospect. Existing completed calls retain their
original analysis; this update does not automatically reprocess or resend them.

## Processing

1. Faster-Whisper produces text with word timestamps.
2. When configured, pyannote separates acoustic voices. Word timestamps split a
   Whisper segment when its speaker changes, instead of assigning the whole segment
   to whichever voice spoke longest.
3. Ollama assigns Agent/Customer roles using introductions, company affiliation and
   the conversation's meaning. The persisted Agent role maps to the existing Caller
   label. Model assignments must include a quote present in that speaker's text
   and medium/high confidence. Unknown IDs, unsupported quotes and low-confidence
   assignments are ignored.
4. With multiple acoustic voices, each voice has a consistent role across its turns.
   Without reliable voice separation, sentence/pause boundaries provide utterances
   for text-only role inference. The UI marks those assignments as content inference.
5. Uncertain or mixed-role speech stays Unassigned. The model cannot reliably
   recover overlapping speakers or split every mixed utterance from text alone.
6. Summary generation has separate structured caller, customer and unassigned
   sections, assembled into the existing `call_summary` string. The CRM payload
   contract is unchanged. Its transcript includes the resulting role labels.

Segments retain original text/timing and gain `role_source`, `role_confidence`, and
accepted `role_evidence`. The audit event `speaker_roles_resolved` records mapping
results, diarization availability and the number of unassigned segments.

Role assignment is an additional local Ollama pass, so processing can take longer.
If that pass fails or times out, the transcript remains available with unassigned
roles and summarization can continue. Roles are model inferences requiring human
review, not verified speaker identities or guaranteed confidence probabilities.

## Enable acoustic diarization

The running worker checked during this implementation had no `HF_TOKEN`, so it
could not run the configured pyannote voice-separation model.

1. Sign in to your Hugging Face account.
2. Accept access conditions for both models:
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
3. Create a read-access token for those models at
   [Hugging Face tokens](https://huggingface.co/settings/tokens).
4. Set it in your private repository-root `.env`:

   ```dotenv
   HF_TOKEN=YOUR_PRIVATE_HUGGING_FACE_TOKEN
   ```

5. Recreate the worker to load the new environment:

   ```powershell
   docker compose up -d --force-recreate worker
   ```

6. Upload a new recording. The first model download may take time. Inspect its
   `speaker_roles_resolved` audit details for `diarization_status: available`.

This is model-download authentication; recordings are processed locally. Never
put the real token in `.env.example`. Model access requirements are documented in
the official [model card](https://huggingface.co/pyannote/speaker-diarization-3.1).

## Verification

Automated tests cover word-level voice changes, customer-first speech, stable
speaker mapping, text-inference labels, ambiguous/unsupported assignments, long-call
batching, role-service failure, and separate summary sections. A synthetic local
Ollama check identified a customer-first introduction and a bank advisor correctly
after using explicit Agent terminology. That does not establish accuracy on real
recordings. Acoustic diarization was not tested live without model access.
