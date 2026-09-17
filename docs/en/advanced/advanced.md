[**Advanced**](./introduction.md) > **Advanced** _(current)_

---

<h3 id="toc">Table of Contents</h3>

- [Command Line Args](#command-line-args)
- [Rate Limiting Configuration Guide](#rate-limiting-configuration-guide)
- [Partial translation](#partial-translation)
- [Specify source and target languages](#specify-source-and-target-languages)
- [Translate with exceptions](#translate-with-exceptions)
- [Custom prompt](#custom-prompt)
- [Custom configuration](#custom-configuration)
- [Skip clean](#skip-clean)
- [Translation cache](#translation-cache)
- [Deployment as a public services](#deployment-as-a-public-services)
- [Authentication and welcome page](#authentication-and-welcome-page)
- [Glossary Support](#glossary-support)

---

#### Command Line Args

Execute the translation command in the command line to generate the translated document `example-mono.pdf` and the bilingual document `example-dual.pdf` in the current working directory. Use Google as the default translation service. More support translation services can find [HERE](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/blob/main/docs/ADVANCED.md#services).

<img src="./../../images/cmd_light.svg" width="580px"  alt="cmd"/>

In the following table, we list all advanced options for reference:

##### Args

| Option                          | Function                                                                               | Example                                                                                                              |
| ------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `input-files`                   | Input PDF files to process                                                              | `pdf2zh_next example.pdf`                                                                                             |
| `--output`                      | Output directory for files                                                              | `pdf2zh_next example.pdf --output /outputpath`                                                                        |
| `--<Services>`                  | Use [**specific service**](./Documentation-of-Translation-Services.md) for translation | `pdf2zh_next example.pdf --openai`<br>`pdf2zh_next example.pdf --deepseek`                                            |
| `--help`, `-h`                  | Show help message and exit                                                              | `pdf2zh_next -h`                                                                                                      |
| `--config-file`                 | Path to the configuration file                                                          | `pdf2zh_next --config-file /path/to/config/config.toml`                                                               |
| `--report-interval`             | Progress report interval in seconds                                                     | `pdf2zh_next example.pdf --report-interval 5`                                                                         |
| `--debug`                       | Use debug logging level                                                                 | `pdf2zh_next example.pdf --debug`                                                                                     |
| `--gui`                         | Interact with GUI                                                                       | `pdf2zh_next --gui`                                                                                                   |
| `--warmup`                      | Only download and verify required assets then exit                                      | `pdf2zh_next example.pdf --warmup`                                                                                    |
| `--generate-offline-assets`     | Generate offline assets package in the specified directory                              | `pdf2zh_next example.pdf --generate-offline-assets /path`                                                             |
| `--restore-offline-assets`      | Restore offline assets package from the specified directory                             | `pdf2zh_next example.pdf --restore-offline-assets /path`                                                              |
| `--version`                     | Show version then exit                                                                  | `pdf2zh_next --version`                                                                                               |
| `--pages`                       | Partial document translation                                                            | `pdf2zh_next example.pdf --pages 1,2,1-,-3,3-5`                                                                       |
| `--lang-in`                     | Source language code                                                                    | `pdf2zh_next example.pdf --lang-in en`                                                                                |
| `--lang-out`                    | Target language code                                                                    | `pdf2zh_next example.pdf --lang-out zh-CN`                                                                            |
| `--min-text-length`             | Minimum text length to translate                                                        | `pdf2zh_next example.pdf --min-text-length 5`                                                                         |
| `--rpc-doclayout`               | RPC service host address for document layout analysis                                   | `pdf2zh_next example.pdf --rpc-doclayout http://127.0.0.1:8000`                                                       |
| `--qps`                         | QPS limit for translation service                                                       | `pdf2zh_next example.pdf --qps 200`                                                                                   |
| `--ignore-cache`                | Ignore translation cache                                                                | `pdf2zh_next example.pdf --ignore-cache`                                                                              |
| `--custom-system-prompt`        | Custom system prompt for translation. Used for `/no_think` in Qwen 3                    | `pdf2zh_next example.pdf --custom-system-prompt "/no_think You are a professional, authentic machine translation engine"` |
| `--glossaries`                  | Glossary file list.                                                                     | `pdf2zh_next example.pdf --glossaries "glossary1.csv,glossary2.csv,glossary3.csv"`                                    |
| `--save-auto-extracted-glossary`| save automatically extracted glossary                                                   | `pdf2zh_next example.pdf --save-auto-extracted-glossary`                                                              |
| `--pool-max-workers`            | Maximum number of workers for translation pool. If not set, will use qps as the number of workers | `pdf2zh_next example.pdf --pool-max-workers 100`                                                           |
| `--term-qps`                    | QPS limit for term extraction translation service. If not set, will follow qps.         | `pdf2zh_next example.pdf --term-qps 20`                                                                               |
| `--term-pool-max-workers`       | Maximum number of workers for term extraction translation pool. If not set or 0, will follow pool_max_workers. | `pdf2zh_next example.pdf --term-pool-max-workers 40`                                                  |
| `--no-auto-extract-glossary`    | Disable auto extract glossary                                                           | `pdf2zh_next example.pdf --no-auto-extract-glossary`                                                                  |
| `--primary-font-family`         | Override primary font family for translated text. Choices: 'serif' for serif fonts, 'sans-serif' for sans-serif fonts, 'script' for script/italic fonts. If not specified, uses automatic font selection based on original text properties. | `pdf2zh_next example.pdf --primary-font-family serif` |
| `--no-dual`                     | Do not output bilingual PDF files                                                       | `pdf2zh_next example.pdf --no-dual`                                                                                   |
| `--no-mono`                     | Do not output monolingual PDF files                                                     | `pdf2zh_next example.pdf --no-mono`                                                                                   |
| `--formular-font-pattern`       | Font pattern to identify formula text                                                   | `pdf2zh_next example.pdf --formular-font-pattern "(MS.*)"`                                                            |
| `--formular-char-pattern`       | Character pattern to identify formula text                                              | `pdf2zh_next example.pdf --formular-char-pattern "(MS.*)"`                                                            |
| `--split-short-lines`           | Force split short lines into different paragraphs                                       | `pdf2zh_next example.pdf --split-short-lines`                                                                         |
| `--short-line-split-factor`     | Split threshold factor for short lines                                                  | `pdf2zh_next example.pdf --short-line-split-factor 1.2`                                                               |
| `--skip-clean`                  | Skip PDF cleaning step                                                                  | `pdf2zh_next example.pdf --skip-clean`                                                                                |
| `--dual-translate-first`        | Put translated pages first in dual PDF mode                                             | `pdf2zh_next example.pdf --dual-translate-first`                                                                      |
| `--disable-rich-text-translate` | Disable rich text translation                                                           | `pdf2zh_next example.pdf --disable-rich-text-translate`                                                               |
| `--enhance-compatibility`       | Enable all compatibility enhancement options                                            | `pdf2zh_next example.pdf --enhance-compatibility`                                                                     |
| `--use-alternating-pages-dual`  | Use alternating pages mode for dual PDF                                                 | `pdf2zh_next example.pdf --use-alternating-pages-dual`                                                                |
| `--watermark-output-mode`       | Watermark output mode for PDF files                                                     | `pdf2zh_next example.pdf --watermark-output-mode no_watermark`                                                        |
| `--max-pages-per-part`          | Maximum pages per part for split translation                                            | `pdf2zh_next example.pdf --max-pages-per-part 50`                                                                     |
| `--translate-table-text`        | Translate table text (experimental)                                                     | `pdf2zh_next example.pdf --translate-table-text`                                                                      |
| `--skip-scanned-detection`      | Skip scanned detection                                                                  | `pdf2zh_next example.pdf --skip-scanned-detection`                                                                    |
| `--ocr-workaround`              | Force translated text to be black and add white background                              | `pdf2zh_next example.pdf --ocr-workaround`                                                                            |
| `--auto-enable-ocr-workaround`  | Enable automatic OCR workaround. If a document is detected as heavily scanned, this will attempt to enable OCR processing and skip further scan detection. See documentation for details. (default: False) | `pdf2zh_next example.pdf --auto-enable-ocr-workaround`                     |
| `--only-include-translated-page`| Only include translated pages in the output PDF. Effective only when --pages is used.  | `pdf2zh_next example.pdf --pages 1-5 --only-include-translated-page`                                                  |
| `--no-merge-alternating-line-numbers` | Disable merging of alternating line numbers and text paragraphs in documents with line numbers | `pdf2zh_next example.pdf --no-merge-alternating-line-numbers`                                                |
| `--no-remove-non-formula-lines` | Disable removal of non-formula lines within paragraph areas                             | `pdf2zh_next example.pdf --no-remove-non-formula-lines`                                                                |
| `--non-formula-line-iou-threshold` | Set IoU threshold for identifying non-formula lines (0.0-1.0)                      | `pdf2zh_next example.pdf --non-formula-line-iou-threshold 0.85`                                                       |
| `--figure-table-protection-threshold` | Set protection threshold for figures and tables (0.0-1.0). Lines within figures/tables will not be processed | `pdf2zh_next example.pdf --figure-table-protection-threshold 0.95`                                        |
| `--skip-formula-offset-calculation` | Skip formula offset calculation during processing          | `pdf2zh_next example.pdf --skip-formula-offset-calculation`                                                           |


##### GUI Args

| Option                          | Function                               | Example                                         |
| ------------------------------- | -------------------------------------- | ----------------------------------------------- |
| `--share`                       | Enable sharing mode                    | `pdf2zh_next --gui --share`                     |
| `--auth-file`                   | Path to the authentication file        | `pdf2zh_next --gui --auth-file /path`           |
| `--welcome-page`                | Path to the welcome html file          | `pdf2zh_next --gui --welcome-page /path`        |
| `--enabled-services`            | Enabled translation services           | `pdf2zh_next --gui --enabled-services "Bing,OpenAI"` |
| `--disable-gui-sensitive-input` | Disable GUI sensitive input            | `pdf2zh_next --gui --disable-gui-sensitive-input` |
| `--disable-config-auto-save`    | Disable automatic configuration saving | `pdf2zh_next --gui --disable-config-auto-save`  |
| `--server-port`                 | WebUI Port                             | `pdf2zh_next --gui --server-port 7860`          |
| `--ui-lang`                     | UI language                            | `pdf2zh_next --gui --ui-lang zh`                |

[⬆️ Back to top](#toc)

---

#### Rate Limiting Configuration Guide

When using translation services, proper rate limiting configuration is crucial to avoid API errors and optimize performance. This guide explains how to configure `--qps` and `--pool-max-workers` parameters based on different upstream service limitations.

> [!TIP]
>
> It is recommended that the pool_size does not exceed 1000. If the pool_size calculated by the following method exceeds 1000, please use 1000.

##### RPM (Requests Per Minute) Rate Limiting

When the upstream service has RPM limitations, use the following calculation:

**Calculation Formula:**
- `qps = floor(rpm / 60)`
- `pool_size = qps * 10`

> [!NOTE]
> The factor of 10 is an empirical coefficient that generally works well for most scenarios.

**Example:**
If your translation service has a limit of 600 RPM:
- `qps = floor(600 / 60) = 10`
- `pool_size = 10 * 10 = 100`

```bash
pdf2zh example.pdf --qps 10 --pool-max-workers 100
```

##### Concurrent Connection Limiting

When the upstream service has concurrent connection limitations (like GLM official service), use this approach:

**Calculation Formula:**
- `pool_size = max(floor(0.9 * official_concurrent_limit), official_concurrent_limit - 20)`
- `qps = pool_size`

**Example:**
If your translation service allows 50 concurrent connections:
- `pool_size = max(floor(0.9 * 50), 50 - 20) = max(45, 30) = 45`
- `qps = 45`

```bash
pdf2zh example.pdf --qps 45 --pool-max-workers 45
```

##### Best Practices

> [!TIP]
> - Always start with conservative values and gradually increase if needed
> - Monitor your service's response times and error rates
> - Different services may require different optimization strategies
> - Consider your specific use case and document size when setting these parameters


[⬆️ Back to top](#toc)

---

#### Partial translation

Use the `--pages` parameter to translate a portion of a document.

- If the page numbers are consecutive, you can write it like this:

```bash
pdf2zh_next example.pdf --pages 1-3
```

```bash
pdf2zh_next example.pdf --pages 25-
```

> [!TIP]
> `25-` includes all pages after page 25. If your document has 100 pages, this is equivalent to `25-100`.
> 
> Similarly, `-25` includes all pages before page 25, which is equivalent to `1-25`.

- If the pages are not consecutive, you can use a comma `,` to separate them.

For example, if you want to translate the first and third pages, you can use the following command:

```bash
pdf2zh_next example.pdf --pages "1,3"
```

- If the pages include both consecutive and non-consecutive ranges, you can also connect them with a comma, like this:

```bash
pdf2zh_next example.pdf --pages "1,3,10-20,25-"
```

This command will translate the first page, the third page, pages 10-20, and all pages from 25 to the end.


[⬆️ Back to top](#toc)

---

#### Specify source and target languages

See [Google Languages Codes](https://developers.google.com/admin-sdk/directory/v1/languages), [DeepL Languages Codes](https://developers.deepl.com/docs/resources/supported-languages)

```bash
pdf2zh_next example.pdf --lang-in en --lang-out ja
```

[⬆️ Back to top](#toc)

---

#### Translate with exceptions

Use regex to specify formula fonts and characters that need to be preserved:

```bash
pdf2zh_next example.pdf --formular-font-pattern "(CM[^RT].*|MS.*|.*Ital)" --formular-char-pattern "(\(|\||\)|\+|=|\d|[\u0080-\ufaff])"
```

Preserve `Latex`, `Mono`, `Code`, `Italic`, `Symbol` and `Math` fonts by default:

```bash
pdf2zh_next example.pdf --formular-font-pattern "(CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|TeX-|rsfs|txsy|wasy|stmary|.*Mono|.*Code|.*Ital|.*Sym|.*Math)"
```

[⬆️ Back to top](#toc)

---

#### Custom prompt

<!-- Note: System prompt is currently not supported. See [this change](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/pull/637). -->

Custom system prompt for translation. It is mainly used to add the '/no_think' instruction of Qwen 3 in the prompt.

```bash
pdf2zh_next example.pdf --custom-system-prompt "/no_think You are a professional and reliable machine translation engine responsible for translating the input text into zh_CN.When translating, strictly follow the instructions below to ensure translation quality and preserve all formatting, tags, and placeholders:"
```

[⬆️ Back to top](#toc)

---

#### Custom configuration

There are multiple ways to modify and import the configuration file.

> [!NOTE]
> **Configuration File Hierarchy**
>
> When modifying the same parameter using different methods, the software will apply changes according to the priority order below. 
>
> Higher-ranked modifications will override lower-ranked ones.
>
> **cli/gui > env > user config file > default config file**

- Modifying Configuration via **Command Line Arguments**

For most cases, you can directly pass your desired settings through command line arguments. Please refer to [Command Line Args](#cmd) for more information.

For example, if you want to enable a GUI window, you can use the following command:

```bash
pdf2zh_next --gui
```

- Modifying Configuration via **Environment Variables**

You can replace the `--` in command line arguments with `PDF2ZH_`, connect parameters using `=`, and replace `-` with `_` as environment variables.

For example, if you want to enable a GUI window, you can use the following command:

```bash
PDF2ZH_GUI=TRUE pdf2zh_next
```

<img src="./../../images/ev_light.svg" width="580px"  alt="env"/>

- User-Specified **Configuration File**

You can specify a configuration file using the command line argument below:

```bash
pdf2zh_next --config-file '/path/config.toml'
```

If you are unsure about the config file format, please refer to the default configuration file described below.

- **Default Configuration File**

The default configuration file is located at `~/.config/pdf2zh`. 
Please do not modify the configuration files in the `default` directory. 
It is strongly recommended to refer to this configuration file's content and use **User-Specified Configuration File** to implement your own configuration file.

> [!TIP]
> - By default, pdf2zh 2.0 automatically saves the current configuration to `~/.config/pdf2zh/config.v3.toml` each time you click the translate button in the GUI. This configuration file will be loaded by default on the next startup.
> - The configuration files in the `default` directory are automatically generated by the program. You can copy them for modification, but please do not modify them directly.
> - Configuration files may include version numbers such as "v2", "v3", etc. These are **configuration file version numbers**, **not** the version number of pdf2zh itself.


[⬆️ Back to top](#toc)

---

#### Skip clean

When this parameter is set to True, the PDF cleaning step will be skipped, which can improve compatibility and avoid some font processing issues.

Usage:

```bash
pdf2zh_next example.pdf --skip-clean
```

Or using environment variables:

```bash
PDF2ZH_SKIP_CLEAN=TRUE pdf2zh_next example.pdf
```

> [!TIP]
> When `--enhance-compatibility` is enabled, Skip clean is automatically enabled.

---

#### Translation cache

PDFMathTranslate caches translated texts to increase speed and avoid unnecessary API calls for same contents. You can use `--ignore-cache` option to ignore translation cache and force retranslation.

```bash
pdf2zh_next example.pdf --ignore-cache
```

[⬆️ Back to top](#toc)

---

#### Deployment as a public services

When deploying a pdf2zh GUI on public services, you should modify the configuration file as described below.

> [!WARNING]
>
> This project has not been professionally audited for security, and may contain security vulnerabilities. Please evaluate the risks and take necessary security measures before deploying on public networks.


> [!TIP]
> - When deploying publicly, both disable_gui_sensitive_input and disable_config_auto_save should be enabled.
> - Separate different available services with *English commas* <kbd>,</kbd> .

A usable configuration is as follows:

```toml title="config.toml"
[basic]
gui = true

[gui_settings]
enabled_services = "Bing,OpenAI"
disable_gui_sensitive_input = true
disable_config_auto_save = true
```

[⬆️ Back to top](#toc)

---

#### Authentication and welcome page

When using Authentication and welcome page to specify which user to use Web UI and custom the login page:

example auth.txt
Each line contains two elements, username, and password, separated by a comma.

```
admin,123456
user1,password1
user2,abc123
guest,guest123
test,test123
```

example welcome.html

```html
<!DOCTYPE html>
<html>
<head>
    <title>Simple HTML</title>
</head>
<body>
    <h1>Hello, World!</h1>
    <p>Welcome to my simple HTML page.</p>
</body>
</html>
```

> [!NOTE]
> welcome page will work if only authentication file is not blank.
> If authentication file is blank, there will be no authentication. :)

A usable configuration is as follows:

```toml title="config.toml"
[basic]
gui = true

[gui_settings]
auth_file = "/path/to/auth/file"
welcome_page = "/path/to/welcome/html/file"
```

[⬆️ Back to top](#toc)

---

#### Glossary Support

PDFMathTranslate supports the glossary table. The glossary tables file should be `csv` file.
There are three columns in file. Here is a demo glossary file:

| source | target  | tgt_lng |
|--------|---------|---------|
| AutoML | 自动 ML  | zh-CN   |
| a,a    | a       | zh-CN   |
| "      | "       | zh-CN   |


For CLI user:
You can use multiple files for glossary. And different files should be split by `,`.

```bash
pdf2zh_next example.pdf --glossaries "glossary1.csv,glossary2.csv,glossary3.csv"
```

For WebUI user:

You can upload your own glossary file now. After you uploaded the file, you can check them by click their name and the content shows below.

[⬆️ Back to top](#toc)
