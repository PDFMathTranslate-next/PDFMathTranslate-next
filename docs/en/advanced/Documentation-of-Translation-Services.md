[**Advanced**](./introduction.md) > **Documentation of Translation Services** _(current)_

---

### Viewing Available Translate Services via Command Line

You can confirm the available translate services and their usage by printing the help message in the command line.

```bash
pdf2zh_next -h
```

At the end of the help message, you can view detailed information about the different translation services.


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

#### DeepSeek thinking mode

DeepSeek thinking is enabled only when `deepseek_thinking_mode` is explicitly set to `enabled`. The default is `disabled`, and the selected mode is sent for any DeepSeek model name; this local mapping does not guarantee that every model supports the parameter.

Selecting **Unset (defaults to disabled)** also sends an explicit disabled mode and does not send `deepseek_reasoning_effort`. The same applies to older configuration files where `deepseek_thinking_mode = "null"`. Those files do not need to be migrated or rewritten: the stored null value remains unset, but now uses the application's disabled default. A configured reasoning effort is sent only while thinking mode is enabled.

#### Tier 2 (Community Support)

**Tier 2 translation engines** are maintained and supported by the community.  
When these engines encounter issues, the project maintainers will not provide direct fixes. Instead, they will label the related issues with `help wanted` and welcome pull requests from contributors to help resolve them.

All engines that are supported by the program but not explicitly listed under Tier 1 are considered Tier 2 translation engines.

#### Deprecated Engines

The following translation engines have been **deprecated** and will no longer be maintained or supported:

1. Bing
2. Google
