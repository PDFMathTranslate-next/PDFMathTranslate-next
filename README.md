<div align="center">

<img src="./docs/images/banner.png" width="320px"  alt="banner"/>

<h2 id="title">PDFMathTranslate</h2>

<p>
  <!-- PyPI -->
  <a href="https://pypi.org/project/pdf2zh-next/">
    <img src="https://img.shields.io/pypi/v/pdf2zh-next"></a>
  <a href="https://pepy.tech/projects/pdf2zh-next">
    <img src="https://static.pepy.tech/badge/pdf2zh-next"></a>
  <a href="https://hub.docker.com/repository/docker/awwaawwa/pdfmathtranslate-next/tags">
    <img src="https://img.shields.io/docker/pulls/awwaawwa/pdfmathtranslate-next"></a>
  <!-- <a href="https://gitcode.com/PDFMathTranslate-next/PDFMathTranslate-next/overview">
    <img src="https://gitcode.com/PDFMathTranslate-next/PDFMathTranslate-next/star/badge.svg"></a> -->
  <!-- <a href="https://huggingface.co/spaces/reycn/PDFMathTranslate-Docker">
    <img src="https://img.shields.io/badge/%F0%9F%A4%97-Online%20Demo-FF9E0D"></a> -->
  <!-- <a href="https://www.modelscope.cn/studios/AI-ModelScope/PDFMathTranslate"> -->
    <!-- <img src="https://img.shields.io/badge/ModelScope-Demo-blue"></a> -->
  <!-- <a href="https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/pulls">
    <img src="https://img.shields.io/badge/contributions-welcome-green"></a> -->
  <a href="https://t.me/+Z9_SgnxmsmA5NzBl">
    <img src="https://img.shields.io/badge/Telegram-2CA5E0?style=flat-squeare&logo=telegram&logoColor=white"></a>
  <!-- License -->
  <a href="./LICENSE">
    <img src="https://img.shields.io/github/license/PDFMathTranslate-next/PDFMathTranslate-next"></a>
  <a href="https://hosted.weblate.org/engage/pdfmathtranslate-next/">
    <img src="https://hosted.weblate.org/widget/pdfmathtranslate-next/svg-badge.svg" alt="translation status" /></a>
    <a href="https://deepwiki.com/PDFMathTranslate-next/PDFMathTranslate-next"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</p>

<a href="https://trendshift.io/repositories/12424" target="_blank"><img src="https://trendshift.io/api/badge/repositories/12424" alt="Byaidu%2FPDFMathTranslate | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

</div>

PDF scientific paper translation and bilingual comparison. Based on [BabelDOC](https://github.com/funstory-ai/BabelDOC). Additionally, this project is also the official reference implementation for calling BabelDOC to perform PDF translation.

- 📊 Preserve formulas, charts, table of contents, and annotations _([preview](#preview))_.
- 🌐 Support [multiple languages](https://pdf2zh-next.com/supported_languages.html), and diverse [translation services](https://pdf2zh-next.com/advanced/Documentation-of-Translation-Services.html).
- 🤖 Provides [commandline tool](https://pdf2zh-next.com/getting-started/USAGE_commandline.html), [interactive user interface](https://pdf2zh-next.com/getting-started/USAGE_webui.html), and [Docker](https://pdf2zh-next.com/getting-started/INSTALLATION_docker.html)

<!-- Feel free to provide feedback in [GitHub Issues](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/issues) or [Telegram Group](https://t.me/+Z9_SgnxmsmA5NzBl). -->

> [!WARNING]
>
> This project is provided "as is" under the [AGPL v3](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/blob/main/LICENSE) license, and no guarantees are provided for the quality and performance of the program. **The entire risk of the program's quality and performance is borne by you.** If the program is found to be defective, you will be responsible for all necessary service, repair, or correction costs.
>
> Due to the maintainers' limited energy, we do not provide any form of usage assistance or problem-solving. Related issues will be closed directly! (Pull requests to improve project documentation are welcome; bugs or friendly issues that follow the issue template are not affected by this)


For details on how to contribute, please consult the [Contribution Guide](https://pdf2zh-next.com/community/Contribution-Guide.html).

<h2 id="preview">Preview</h2>

<div align="center">
<!-- <img src="./docs/images/preview.gif" width="80%"  alt="preview"/> -->
<img src="https://s.immersivetranslate.com/assets/r2-uploads/images/babeldoc-preview.png" width="80%"/>
</div>

<h2 id="demo">Online Service 🌟</h2>

You can try our application out using either of the following services:

- [Immersive Translate - BabelDOC](https://app.immersivetranslate.com/babel-doc/) Free usage quota is available; please refer to the FAQ section on the page for details.

<h2 id="install">Installation and Usage</h2>

### Installation

1. [**Windows EXE**](https://pdf2zh-next.com/getting-started/INSTALLATION_winexe.html) <small>Recommand for Windows</small>
2. [**Docker**](https://pdf2zh-next.com/getting-started/INSTALLATION_docker.html) <small>Recommand for Linux</small>
3. [**uv** (a Python package manager)](https://pdf2zh-next.com/getting-started/INSTALLATION_uv.html) <small>Recommand for macOS</small>

---

### Usage

1. [Using **WebUI**](https://pdf2zh-next.com/getting-started/USAGE_webui.html)
2. [Using **Zotero Plugin**](https://github.com/guaguastandup/zotero-pdf2zh) (Third party program)
3. [Using **Commandline**](https://pdf2zh-next.com/getting-started/USAGE_commandline.html)

For different use cases, we provide distinct methods to use our program. Check out [this page](./getting-started/getting-started.md) for more information.

<h2 id="usage">Advanced Options</h2>

For detailed explanations, please refer to our document about [Advanced Usage](https://pdf2zh-next.com/advanced/advanced.html) for a full list of each option.

<h2 id="translation-quality">Translation Quality Tuning</h2>

### Temperature (Creativity Control)

Higher temperature produces more natural, varied translations; lower temperature is more literal and deterministic.

```bash
# OpenAI / OpenAI-compatible (DeepSeek, Gemini, Grok, etc.)
pdf2zh input.pdf --openai --openai-model gpt-4o --openai-temperature 0.3

# SiliconFlow
pdf2zh input.pdf --siliconflow --siliconflow-model Qwen/Qwen2.5-7B-Instruct \
  --siliconflow-temperature 0.3 --siliconflow-send-temperature
```

Recommended starting points:
- **0.1-0.2**: Conservative, minimal deviation from literal translation
- **0.3-0.4**: Good balance of accuracy and natural fluency (recommended)
- **0.5+**: More creative/phrasal, better for literary text

### Custom System Prompt

Override the default translation instructions entirely. Useful for:
- Adding model-specific prefixes (e.g., Qwen 3's `/no_think` to disable chain-of-thought)
- Domain-specific guidance (e.g., medical/legal translation style)

```bash
# Disable chain-of-thought on Qwen 3 models
pdf2zh input.pdf --openai --openai-model qwen3-8b \
  --custom-system-prompt "/no_think"

# Custom domain instruction
pdf2zh input.pdf --openai \
  --custom-system-prompt "You are a medical translator. Prioritize terminology accuracy."
```

### Translation Prompt

The default prompt now encourages semantic translation for academic/technical terms rather than mechanical transliteration, and prioritizes natural coherence in the target language. Formulas, placeholders (like `{{1}}`), code snippets, and proper nouns are preserved automatically.

### Glossary / Term Extraction

For consistent terminology, use the glossary feature:

```bash
# Auto-extract terms (default when using LLM engines)
pdf2zh input.pdf --openai

# Provide custom glossary file
pdf2zh input.pdf --openai --glossaries /path/to/glossary.txt
```

<h2 id="downstream">Secondary Development (APIs)</h2>

<!-- <!-- For downstream applications, please refer to our document about [API Details](./docs/APIS.md) for futher information about: -->

- [Python API](./docs/en/advanced/API/python.md), how to use the program in other Python programs
<!-- - [HTTP API](./docs/APIS.md#api-http), how to communicate with a server with the program installed -->

<h2 id="langcode">Language Code</h2>

If you don't know what code to use to translate to the language you need, check out [this documentation](https://pdf2zh-next.com/advanced/Language-Codes.html)

<h2 id="acknowledgement">Acknowledgements</h2>

- [Immersive Translation](https://immersivetranslate.com) sponsors monthly Pro membership redemption codes for active contributors to this project, see details at: [CONTRIBUTOR_REWARD.md](https://github.com/funstory-ai/BabelDOC/blob/main/docs/CONTRIBUTOR_REWARD.md)

- [SiliconFlow](https://siliconflow.cn) provides a free translation service for this project, powered by large language models (LLMs).

- 1.x version: [Byaidu/PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate)


- backend: [BabelDOC](https://github.com/funstory-ai/BabelDOC)

- PDF Library: [PyMuPDF](https://github.com/pymupdf/PyMuPDF)

- PDF Parsing: [Pdfminer.six](https://github.com/pdfminer/pdfminer.six)

- PDF Preview: [Gradio PDF](https://github.com/freddyaboulton/gradio-pdf)

- Layout Parsing: [DocLayout-YOLO](https://github.com/opendatalab/DocLayout-YOLO)

- PDF Standards: [PDF Explained](https://zxyle.github.io/PDF-Explained/), [PDF Cheat Sheets](https://pdfa.org/resource/pdf-cheat-sheets/)

- Multilingual Font: see [BabelDOC-Assets](https://github.com/funstory-ai/BabelDOC-Assets)

- [Asynchronize](https://github.com/multimeric/Asynchronize/tree/master?tab=readme-ov-file)

- [Rich logging with multiprocessing](https://github.com/SebastianGrans/Rich-multiprocess-logging/tree/main)

- Documentation i18n using [Weblate](https://hosted.weblate.org/projects/pdfmathtranslate-next/) 


<h2 id="conduct">Before submit your code</h2>

We welcome the active participation of contributors to make pdf2zh better. Before you are ready to submit your code, please refer to our [Code of Conduct](https://pdf2zh-next.com/community/CODE_OF_CONDUCT.html) and [Contribution Guide](https://pdf2zh-next.com/community/Contribution-Guide.html).

<h2 id="contrib">Contributors</h2>

<!-- <a href="https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/graphs/contributors">
  <img src="https://opencollective.com/PDFMathTranslate/contributors.svg?width=890&button=false" />
</a> -->

<!-- ![Alt](https://repobeats.axiom.co/api/embed/45529651750579e099960950f757449a410477ad.svg "Repobeats analytics image") -->

<h2 id="star_hist">Star History</h2>

<a href="https://star-history.com/#PDFMathTranslate-next/PDFMathTranslate-next&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=PDFMathTranslate-next/PDFMathTranslate-next&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=PDFMathTranslate-next/PDFMathTranslate-next&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=PDFMathTranslate-next/PDFMathTranslate-next&type=Date"/>
 </picture>
</a>
