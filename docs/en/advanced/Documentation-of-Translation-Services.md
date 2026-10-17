[**Advanced**](./introduction.md) > **Documentation of Translation Services** _(current)_

---

### Viewing Available Translate Services via Command Line

You can confirm the available translate services and their usage by printing the help message in the command line.

```bash
pdf2zh_next -h
```

At the end of the help message, you can view detailed information about the different translation services.

### DeepSeek translation with text and final PDF visual review

Select **DeepSeekReview** in the WebUI, or use `--deepseekreview` in the CLI,
to translate with DeepSeek, review and revise the draft against the source, then
visually review every final PDF page after BabelDOC typesets it. This is an opt-in
engine with two mandatory reviews using the official
DeepSeek API. The existing **DeepSeek** engine still performs one pass.
The review uses DeepSeek's [JSON output](https://api-docs.deepseek.com/guides/json_mode/)
API; the default model follows its [official model documentation](https://api-docs.deepseek.com/quick_start/pricing/).

Set `PDF2ZH_DEEPSEEK_REVIEW_API_KEY` in your environment rather than passing a
secret on the command line. Then run:

```bash
pdf2zh_next paper.pdf --deepseekreview \
  --deepseek-review-domain "reinforcement learning" \
  --deepseek-review-context "DreamerV3; keep Dreamer as a proper name; use consistent actor/critic terminology."
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--deepseek-review-api-key` | Unset | DeepSeek API key; masked in the WebUI. Prefer the environment variable above. |
| `--deepseek-review-model` | `deepseek-flash` | Model for both translation and review. |
| `--deepseek-review-domain` | Empty | Optional subject area; inferred from available context when omitted. |
| `--deepseek-review-context` | Empty | Optional document background or terminology guidance. |
| `--deepseek-review-translation-prompt` | Built-in academic translator | Custom system instructions for the initial translation. |
| `--deepseek-review-prompt` | Built-in scientific editor | Custom system instructions for reviewing the draft. |
| `--deepseek-review-visual-model` | `deepseek-flash` | Image-capable model for final PDF visual review; uses the same key. |
| `--deepseek-review-visual-prompt` | Built-in visual proofreader | Custom instructions for reviewing the final page images. |

The two passes use independent system prompts. Translation focuses on faithful,
fluent academic text; review compares source and draft for errors and revises the
text. Both receive the domain/background and the original request. Custom prompts
retain mandatory output-format and placeholder rules. Changing either prompt
invalidates the corresponding reviewed-response cache. Both passes continue to
use the official DeepSeek API with the configured key and model.

The reviewer receives the complete original translation request, including any
document/section titles, paragraph batch and glossary supplied by BabelDOC, plus
the draft and your domain/background. It checks technical terminology, omissions,
negation and exceptions, numbers and units, then returns corrected translated
text. This does not give the reviewer access to the entire PDF or external
references. Use a [glossary](./advanced.md) for consistent terminology throughout
a document.

The translation and text-review passes use the same API key and text model.
Expect roughly twice as many text API requests; text review also includes the draft
and the original request. Both passes count toward the configured QPS limit and
token totals. If this engine is also used for automatic term extraction, those
LLM requests are text-reviewed too; select a separate term-extraction engine to
avoid that additional pass. Final page images generate additional billed vision
requests and tokens, with the same key and a separately configurable visual model.

Only the final reviewed response is cached, separately from single-pass
translations and from other review prompts, models, domains and backgrounds.
Invalid, empty or incomplete review responses, changed batch IDs/schema, or
changed formula/style placeholders raise an error and are not cached as reviewed
translations. BabelDOC may retry according to its own translation rules. If any
translation request still has an unresolved failure at the end, this engine blocks
completion, including when BabelDOC falls back to source text. Successful retries
or reviewed cache hits resolve the corresponding failure. These checks protect
structure, but cannot guarantee scientific accuracy; review important claims
against the source.

#### Mandatory review of the rendered final pages

The textual reviewer sees strings and context before typesetting. It cannot catch
a font that renders incorrect letters while the PDF text layer remains correct.
After typesetting, this engine renders each actual output page with PyMuPDF and
sends PNG images of the source page and final page to DeepSeek's
[vision API](https://api-docs.deepseek.com/guides/vision/). Side-by-side bilingual
pages also include separate left/right detail images. The reviewer checks visible
glyphs, formulas, superscripts, numbers, clipping, overlaps, and missing content.
Extracted text is explicitly labeled untrusted reference data. This is direct
model review of page images, without an OCR dependency.

Every generated output variant is checked, including monolingual, bilingual and
additional unwatermarked files. Page mapping honors page selection, omission of
unselected pages, and alternating bilingual pages. The visual model defaults to
`deepseek-flash` independently of the text model; choose a model that supports
image input. There is no visual-review cache: final pages are checked even when
their translated text came from cache. Plain DeepSeek and other engines retain
their existing behavior.

The engine emits `finish` and exposes successful GUI downloads only after both
reviews complete and every page receives a valid visual `pass`. Defects,
uncertainty, malformed/truncated responses, API failures, inconsistent page counts,
or PDFs modified during review block completion. The generated PDFs remain on
disk for inspection/correction; they are not labeled as approved. A review does
not automatically rewrite a PDF. Correct a flagged artifact and rerun visual
review before treating it as finished. Model judgments may miss defects or raise
false alarms, so inspect the saved evidence for important findings.

A unique `deepseek-visual-review-*` directory beside the outputs retains page
images and `report.json`, including file SHA-256 hashes, source/output page numbers,
verdicts, normalized issue rectangles, coverage, and token totals. Reports contain
document content and should be handled like the PDFs themselves. Credentials and
inline image payloads are not included. Interrupted/failed reviews remain marked
incomplete rather than passing silently.

The CLI logs progress and the report path. Python stream consumers receive
`visual_review_progress` events, followed on success by a normal `finish` event
with `text_review`, `visual_review` (status, report path, page count, token usage),
and `token_usage["visual_review"]`. The WebUI displays visual progress and a
completion notification; the reports remain alongside the server's output files.


---

### Translation Engine Support Policy

#### Tier 1 (Official Support)

**Tier 1 translation engines** are directly maintained by the project maintainers. Although the maintainers do **not use this project regularly**, they will rely on GitHub issues to identify problems. When any of these engines encounter issues, the maintainers will fix them as soon as possible to ensure stability and reliability.


Currently supported Tier 1 translation engines include:
1. SiliconFlowFree
2. OpenAI
3. AliyunDashScope
4. DeepSeek
5. SiliconFlow
6. Zhipu
7. OpenAICompatible

#### Tier 2 (Community Support)

**Tier 2 translation engines** are maintained and supported by the community.  
When these engines encounter issues, the project maintainers will not provide direct fixes. Instead, they will label the related issues with `help wanted` and welcome pull requests from contributors to help resolve them.

All engines that are supported by the program but not explicitly listed under Tier 1 are considered Tier 2 translation engines.

#### Deprecated Engines

The following translation engines have been **deprecated** and will no longer be maintained or supported:

1. Bing
2. Google
