# Are the 12 ABSENT questions really absent from the corpus?

Corpus read from the live server: 17 files (15 itsdangerous source and test files, the Python
`hmac` docs page, the HMAC Wikipedia article), 1,954 lines, 332 twelve-line windows. Each question
was tried 5 ways (the golden question plus 4 rewordings): cosine over every window (`atlas-embed`
embeddings), BM25 over the same windows, grep for distinguishing terms in the raw text, and the
server's own `/search`. Data and every grep hit: `verify_absent.json`; script: `evals/verify_absent.py`.

| Question | Best cosine (5 variants) | Over 0.80? | Grep hits | Near-match a person would call relevant | Call |
| --- | --- | --- | --- | --- | --- |
| F-A01 revoke a token | 0.545 | no | 0 | none (expiry via `max_age` exists, revocation does not) | TRULY ABSENT |
| F-A02 Flask sessions | 0.584 | no | 1 | `html_theme = "flask"` in docs conf only | TRULY ABSENT |
| F-A03 library to encrypt the payload | 0.459 | no | 6 | HMAC article says "HMAC does not encrypt the message"; no library named | TRULY ABSENT (see note) |
| F-A04 HMAC in Java | 0.700 | no | 1 | a bare "Java implementation" link in the Wikipedia list; no code | TRULY ABSENT |
| F-A05 HMAC-SHA256 of 'hello' | 0.688 | no | 0 | none; the digest is not in the text (it is computed, not looked up) | TRULY ABSENT |
| F-A06 companies in production | 0.486 | no | 1 | "used by" in a base64 comment only | TRULY ABSENT |
| F-A07 conda on Windows | 0.395 | no | 1 | a "Windows raises OSError" code comment; no install docs ingested | TRULY ABSENT |
| F-A08 HMAC vs BLAKE2 speed | 0.586 | no | 1 | "faster" in `hmac.digest` docs, unrelated to BLAKE2 | TRULY ABSENT |
| F-A09 licence | 0.393 | no | 0 | no LICENSE or README ingested | TRULY ABSENT |
| F-A10 asyncio | 0.469 | no | 0 | none | TRULY ABSENT |
| V-03 2022 World Cup | 0.200 | no | 0 | none | TRULY ABSENT |
| V-05 "why does Signer.sign encrypt with AES?" | 0.662 | no | 3 | the corpus refutes the premise: "HMAC does not encrypt the message" | **AMBIGUOUS** |

**No chunk reaches cosine 0.80 (highest 0.70, on a list of implementation links), no exact keyword
match answers any question, and none is ANSWERABLE.** So there is no undercounted headroom from
this bucket, and the refusal rate is not overstated by it. I changed nothing in the golden set.

## The two that need a human call

- **V-05 (false premise).** Its own rationale says "the question should be corrected". The corpus
  has the evidence to correct it (the HMAC article and `Signer` signing with HMAC), so a good
  answer is a cited correction, not a refusal. The set expects ABSENT, which counts a correction
  as a failure. Either relabel it (state: false premise, expected: corrects, with the HMAC lines as
  relevant paths) or keep it and accept that a correct answer scores as wrong. Recommend relabelling.
- **F-A03 (which library encrypts the payload).** The corpus says HMAC does not encrypt, and the
  set uses those same lines as targets for M-10 ("is the payload encrypted?", INFERRED). It does
  not name any library, so the asked question is absent and I left it ABSENT; but the pair is worth
  a look so the two labels stay consistent.

## Limits

Windows were 12 lines with a step of 6, not the server's symbol chunks, so a cosine here is not the
server's own score (its `/search` scores, shown in the data, top out at 0.57 for these). The corpus
is what is ingested now: the repository's README and LICENSE are not in it, so F-A07 and F-A09 are
absent from the corpus though true of the upstream project. Variants were written by me, not
generated blindly; five is not exhaustive.
