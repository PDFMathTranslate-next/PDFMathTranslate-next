import contextlib
import json
import logging
import re
from abc import ABC
from abc import abstractmethod

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.translator.base_rate_limiter import BaseRateLimiter
from pdf2zh_next.translator.cache import TranslationCache

logger = logging.getLogger(__name__)


_CODE_BLOCK_CLASS_CODE = "code"
_CODE_BLOCK_CLASS_TEXT = "text"
_CODE_BLOCK_CLASS_AMBIGUOUS = "ambiguous"
_CODE_BLOCK_LLM_SKIP_CONFIDENCE = 0.75
_STYLE_TAG_RE = re.compile(r"</?style\b[^>]*>", re.IGNORECASE)
_BABELDOC_TEXT_MARKER = "Now translate the following text:"
_CODE_BLOCK_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_CODE_KEYWORD_RE = re.compile(
    r"\b("
    r"def|class|if|elif|else|for|while|try|except|finally|return|yield|"
    r"import|from|with|lambda|"
    r"const|let|var|function|async|await|public|private|protected|static|void|"
    r"int|float|double|string|bool|boolean|char|long|short|byte|new|this|"
    r"struct|enum|interface|type|record|package|namespace|using|include|"
    r"fn|impl|trait|pub|mut|use|mod|match|func|defer|go|map|chan|select|"
    r"case|switch|default|break|continue|require|module"
    r")\b",
    re.IGNORECASE,
)
_SQL_LINE_RE = re.compile(
    r"^\s*(SELECT|WITH|FROM|WHERE|JOIN|INNER JOIN|LEFT JOIN|RIGHT JOIN|"
    r"INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|GROUP BY|ORDER BY|VALUES|SET)\b",
    re.IGNORECASE,
)
_SQL_SYNTAX_RE = re.compile(
    r"\b(FROM|WHERE|JOIN|ON|VALUES|SET|TABLE|INDEX|VIEW|DATABASE|SCHEMA|"
    r"INTO|GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING|AS\s*\(|PRIMARY\s+KEY)\b|[=*,;]",
    re.IGNORECASE,
)
_SQL_CREATE_RE = re.compile(
    r"^\s*CREATE\s+(?:TABLE|INDEX|VIEW|DATABASE|SCHEMA|FUNCTION|PROCEDURE|"
    r"TRIGGER)\b",
    re.IGNORECASE,
)
_SHELL_COMMAND_RE = re.compile(
    r"^\s*(?:[$>#]\s*)?"
    r"(?:sudo\s+)?"
    r"(git|pip|pip3|uv|npm|npx|yarn|pnpm|node|deno|bun|python|python3|"
    r"pytest|tox|poetry|pipenv|virtualenv|conda|mamba|cargo|rustup|go|mvn|"
    r"gradle|make|cmake|ninja|bazel|gcc|g\+\+|clang|clang\+\+|dotnet|java|"
    r"javac|php|ruby|gem|bundle|composer|perl|lua|Rscript|curl|wget|http|"
    r"ssh|scp|sftp|rsync|tar|gzip|gunzip|zip|unzip|7z|docker|docker-compose|"
    r"podman|kubectl|helm|minikube|kind|terraform|ansible|ansible-playbook|"
    r"aws|az|gcloud|gh|glab|heroku|vercel|netlify|apt|apt-get|dnf|yum|brew|"
    r"pacman|apk|zypper|systemctl|service|journalctl|ps|top|htop|kill|killall|"
    r"ip|ifconfig|ping|traceroute|netstat|ss|nslookup|dig|psql|mysql|sqlite3|"
    r"redis-cli|mongo|mongosh|openssl|ffmpeg|convert|magick|ros2|rosdep|"
    r"colcon|cd|ls|pwd|mkdir|cp|mv|rm|cat|less|more|head|tail|grep|rg|sed|"
    r"awk|find|xargs|chmod|chown|ln|touch|export|source|echo|printf|read)\b",
    re.IGNORECASE,
)
_WINDOWS_COMMAND_RE = re.compile(
    r"^\s*(?:[A-Za-z]:\\[^>]*>\s*)?"
    r"(cd|dir|copy|xcopy|robocopy|move|del|erase|ren|type|setx|where|md|"
    r"mkdir|rd|rmdir|cls|echo|call|start|cmd|powershell|pwsh|py|python|pip|"
    r"winget|choco|scoop|msbuild|nuget|schtasks|tasklist|taskkill|net|netsh|"
    r"reg|sc|wmic|bcdedit|dism|sfc|certutil|ipconfig|ping|tracert|nslookup)\b",
    re.IGNORECASE,
)
_POWERSHELL_COMMAND_RE = re.compile(
    r"^\s*(?:PS\s+[A-Za-z]:\\[^>]*>\s*)?"
    r"(?:Get|Set|New|Remove|Copy|Move|Start|Stop|Restart|Invoke|Import|Export|"
    r"Select|Where|ForEach|Test|Join|Split|Write|Read|Add|Clear|ConvertTo|"
    r"ConvertFrom)-[A-Za-z]+\b",
    re.IGNORECASE,
)
_DECLARATION_LINE_RE = re.compile(
    r"^\s*(?:@[\w.]+(?:\([^)]*\))?\s*)*"
    r"(?:(?:export|async|public|private|protected|static|final|abstract|"
    r"inline|constexpr|virtual|override|internal|sealed|partial|pub|unsafe)\s+)*"
    r"(?:local\s+)?"
    r"(?:def|class|interface|enum|struct|record|trait|impl|namespace|package|"
    r"func|fn|function|type)\b",
    re.IGNORECASE,
)
_IMPORT_LINE_RE = re.compile(
    r"^\s*(?:#\s*include\b|import\s+[\w.*{},\s]+|from\s+\S+\s+import\b|"
    r"using\s+[\w.:]+|use\s+[\w.:{}]+|require\s*\(|module\s+\w+)"
)
_METHOD_SIGNATURE_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final|abstract|async|inline|"
    r"constexpr|virtual|override|internal|sealed|partial)\s+)*"
    r"(?:void|int|float|double|string|bool|boolean|char|long|short|byte|"
    r"[A-Z]\w+(?:<[^>]+>)?)\s+[$A-Za-z_]\w*\s*\([^)]*\)\s*(?:\{|;)?\s*$",
    re.IGNORECASE,
)
_RUBY_COMMAND_RE = re.compile(
    r"^\s*(?:puts|print|raise|require|include|extend|attr_reader|attr_writer|"
    r"attr_accessor)\b"
)
_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:[$A-Za-z_][\w.$]*(?:\[[^\]]*\])?\s*)"
    r"(?:=|:=|\+=|-=|\*=|/=|=>)\s*\S"
)
_VARIABLE_DECL_RE = re.compile(
    r"^\s*(?:(?:const|let|var|final|auto|int|float|double|string|bool|boolean|"
    r"char|long|short|byte|String|Object|List|Map|Set|Dictionary|HashMap)\s+"
    r"[$A-Za-z_][\w$]*\s*(?:=|;|,|\(|\[)|"
    r"(?:[A-Z]\w+(?:<[^>]+>)?)\s+[$A-Za-z_][\w$]*\s*(?:=|;|\[))"
)
_STATEMENT_LINE_RE = re.compile(
    r"^\s*(?:return|yield|break|continue|throw|raise|echo|print|puts)\b"
)
_CALL_LINE_RE = re.compile(
    r"^\s*(?:await\s+)?[$A-Za-z_][\w.$]*(?:->|::|\.)?[\w$]*"
    r"\s*\([^)]*\)\s*;?\s*$"
)
_BLOCK_DELIMITER_LINE_RE = re.compile(r"^\s*(?:end|do|else|\{|\})\s*;?\s*$")
_SHEBANG_RE = re.compile(r"^\s*#!")
_SHELL_CONTROL_LINE_RE = re.compile(
    r"^\s*(?:if|then|elif|else|fi|for|while|until|do|done|case|esac)\b|;\s*do\s*$"
)
_COMMENT_LINE_RE = re.compile(r"^\s*(#|//|/\*|\*|--|<!--)")
_CODE_OPERATOR_RE = re.compile(r"(==|!=|<=|>=|=>|->|::|&&|\|\||[{}\[\]();=<>+\-*/])")
_COMMAND_OPERATOR_RE = re.compile(r"(\s-{1,2}\w|/[A-Za-z?]|\||&&|[<>]|\\$|`$|\^$)")
_GENERIC_COMMAND_HINT_RE = re.compile(r"^\s*[\w./:-]+\s+(?:-{1,2}\w|/[A-Za-z?])")
_COMMAND_PROMPT_RE = re.compile(
    r"^(?:[$>#]\s*|PS\s+[A-Za-z]:\\[^>]*>\s*|[A-Za-z]:\\[^>]*>\s*)"
)
_COMMAND_WRAPPER_RE = re.compile(r"^(?:sudo|doas|env|time|nohup|command|builtin)\b")
_ENV_ASSIGNMENT_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S+$")
_EXECUTABLE_TOKEN_RE = re.compile(
    r"^(?:\.{1,2}[\\/]|~[\\/]|[A-Za-z]:\\|\\\\|[\w.-]+\."
    r"(?:exe|cmd|bat|ps1|psm1|sh|bash|zsh|fish|py|js|mjs|cjs|ts|rb|pl|php|jar))"
)
_COMMAND_SUBCOMMAND_RE = re.compile(
    r"^(add|addr|apply|archive|build|check|clean|clone|config|configure|copy|cp|"
    r"create|delete|deploy|describe|diff|exec|fmt|get|grep|init|install|list|"
    r"login|logout|logs|node|package|plan|port-forward|pull|push|query|remove|restart|"
    r"restore|run|s3|serve|show|start|status|stop|sync|test|update|upgrade|"
    r"version|watch|x509)\b",
    re.IGNORECASE,
)
_PROSE_COMMAND_WORD_RE = re.compile(
    r"^(is|are|was|were|be|being|been|can|could|should|would|will|may|might|"
    r"when|while|because|after|before|that|this|the|a|an|and|or|in|on|as|"
    r"helps|uses|shows|means|describes|returns|lists|runs)$",
    re.IGNORECASE,
)
_COMMAND_ARGUMENT_RE = re.compile(
    r"^(?:-{1,2}\w|/[A-Za-z?]|[\w.-]+=.+|[\w./:-]+\.(?:txt|log|json|ya?ml|toml|"
    r"xml|ini|cfg|conf|py|js|ts|sh|bash|ps1|bat|cmd|exe|dll|so|dylib|jar|zip|"
    r"tar|gz|pdf|png|jpe?g|mp4|mp3|wav|csv|db|sqlite|pem|crt|key)|//|\.{1,2}/|"
    r"[A-Za-z]:\\|\\\\|~[/\\])",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"(^|[\s=:])(~?/|\.{1,2}/|[A-Za-z]:\\|\\\\|[\w.-]+/[\w.-]+)")
_STRUCTURED_DATA_LINE_RE = re.compile(
    r"^\s*(?:[{}\[\],]+|[\"']?[\w.-]+[\"']?\s*[:=]\s*\S.*[,]?|"
    r"</?[\w:-]+(?:\s+[\w:-]+=(?:\"[^\"]*\"|'[^']*'))*\s*/?>)\s*$"
)
_JSON_OBJECT_LINE_RE = re.compile(r"^\s*[\[{].*[\"']?[\w.-]+[\"']?\s*:.*[\]}]\s*,?\s*$")
_MAKEFILE_LINE_RE = re.compile(r"^\s*[\w./-]+\s*:\s*(?:$|[\w./-])")
_DOCKERFILE_LINE_RE = re.compile(
    r"^\s*(FROM|RUN|CMD|LABEL|EXPOSE|ENV|ADD|COPY|ENTRYPOINT|VOLUME|USER|"
    r"WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL)\b",
    re.IGNORECASE,
)
_TEXT_CALLOUT_RE = re.compile(
    r"^\s*(tips?|notes?|notice|warning|caution|important|remember)\s*:?\s*$",
    re.IGNORECASE,
)
_TEXT_CALLOUT_PREFIX_RE = re.compile(
    r"^\s*(tips?|notes?|notice|warning|caution|important|remember)\s*:\s+\S",
    re.IGNORECASE,
)
_PLAIN_PROSE_RE = re.compile(r"[A-Za-z][A-Za-z ,.'\"()/-]{12,}[.!?]?$")
_PROSE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")
_PROSE_SENTENCE_WORD_RE = re.compile(
    r"\b(the|a|an|this|that|these|those|you|we|it|its|they|there|from|with|"
    r"to|and|or|if|when|while|will|can|must|should|have|has|is|are|be|as|so|"
    r"because|however|just|need|use|uses|using)\b",
    re.IGNORECASE,
)


def _extract_babeldoc_text_to_translate(text: str) -> str | None:
    if not isinstance(text, str):
        return None

    marker_index = text.rfind(_BABELDOC_TEXT_MARKER)
    if marker_index == -1:
        return None

    prompt_prefix = text[:marker_index]
    if "## Rules" not in prompt_prefix or "## Output" not in prompt_prefix:
        return None

    return text[marker_index + len(_BABELDOC_TEXT_MARKER) :].lstrip("\r\n")


def _command_parts(stripped_line: str) -> list[str]:
    line = _COMMAND_PROMPT_RE.sub("", stripped_line).strip()
    parts = line.split()
    while parts and (
        _COMMAND_WRAPPER_RE.match(parts[0]) or _ENV_ASSIGNMENT_PREFIX_RE.match(parts[0])
    ):
        parts = parts[1:]
    return [part.strip("\"'") for part in parts]


def _has_command_syntax(stripped_line: str, parts: list[str]) -> bool:
    return (
        bool(_COMMAND_OPERATOR_RE.search(stripped_line))
        or bool(_PATH_RE.search(stripped_line))
        or any(_COMMAND_ARGUMENT_RE.search(part) for part in parts[1:])
    )


def _has_sql_syntax(stripped_line: str) -> bool:
    match = _SQL_LINE_RE.search(stripped_line)
    if not match:
        return False

    keyword = " ".join(match.group(1).upper().split())
    if (
        match.group(1) != match.group(1).upper()
        and len(_PROSE_WORD_RE.findall(stripped_line)) > 5
    ):
        return False
    if keyword == "SELECT":
        return bool(
            re.search(
                r"\b(FROM|WHERE|JOIN|GROUP\s+BY|ORDER\s+BY|LIMIT)\b|[*]",
                stripped_line,
                re.IGNORECASE,
            )
        ) or (
            len(_PROSE_WORD_RE.findall(stripped_line)) <= 5
            and bool(re.search(r"[,;]", stripped_line))
        )
    if keyword == "CREATE":
        return bool(_SQL_CREATE_RE.search(stripped_line))
    if keyword == "WITH":
        return bool(re.search(r"\bAS\s*\(|\bSELECT\b", stripped_line, re.IGNORECASE))
    if keyword == "FROM":
        return len(_PROSE_WORD_RE.findall(stripped_line)) <= 5 or bool(
            re.search(r"\bJOIN\b|;", stripped_line, re.IGNORECASE)
        )
    if keyword in {"JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN"}:
        return len(_PROSE_WORD_RE.findall(stripped_line)) <= 6 or bool(
            re.search(r"\bON\b|[=,;]", stripped_line, re.IGNORECASE)
        )
    if keyword == "WHERE":
        return len(_PROSE_WORD_RE.findall(stripped_line)) <= 6 or bool(
            re.search(
                r"(?:=|<>|!=|<=|>=|<|>)|\b(LIKE|IS\s+NULL|IN\s*\()",
                stripped_line,
                re.IGNORECASE,
            )
        )
    if keyword in {"GROUP BY", "ORDER BY", "VALUES", "SET"}:
        return len(_PROSE_WORD_RE.findall(stripped_line)) <= 6 or bool(
            re.search(r"[=(),*;]", stripped_line)
        )

    return bool(_SQL_SYNTAX_RE.search(stripped_line))


def _is_dockerfile_line(stripped_line: str) -> bool:
    match = _DOCKERFILE_LINE_RE.search(stripped_line)
    if not match:
        return False

    instruction = match.group(1)
    remainder = stripped_line[match.end() :].strip()
    if not remainder:
        return False
    first_arg = remainder.split()[0]
    if _PROSE_COMMAND_WORD_RE.match(first_arg):
        return False
    if (
        instruction != instruction.upper()
        and len(_PROSE_WORD_RE.findall(stripped_line)) > 4
    ):
        return False
    return True


def _looks_like_prose_line(stripped_line: str) -> bool:
    if not stripped_line:
        return False
    if _TEXT_CALLOUT_RE.match(stripped_line) or _TEXT_CALLOUT_PREFIX_RE.match(
        stripped_line
    ):
        return True
    if (
        _COMMENT_LINE_RE.search(stripped_line)
        or _COMMAND_PROMPT_RE.match(stripped_line)
        or _has_sql_syntax(stripped_line)
        or _DECLARATION_LINE_RE.search(stripped_line)
        or _IMPORT_LINE_RE.search(stripped_line)
        or _METHOD_SIGNATURE_RE.search(stripped_line)
        or _ASSIGNMENT_RE.search(stripped_line)
        or _VARIABLE_DECL_RE.search(stripped_line)
        or _CALL_LINE_RE.search(stripped_line)
        or _JSON_OBJECT_LINE_RE.search(stripped_line)
        or _is_dockerfile_line(stripped_line)
    ):
        return False

    words = _PROSE_WORD_RE.findall(stripped_line)
    word_count = len(words)
    if word_count < 4:
        return False

    sentence_words = bool(_PROSE_SENTENCE_WORD_RE.search(stripped_line))
    sentence_punctuation = bool(re.search(r"[,.;:!?]", stripped_line))
    operator_count = len(_CODE_OPERATOR_RE.findall(stripped_line))

    if word_count >= 10 and sentence_words:
        return True
    if word_count >= 7 and sentence_words and sentence_punctuation:
        return True
    if word_count >= 4 and sentence_words and sentence_punctuation:
        return True
    if word_count >= 5 and sentence_words and stripped_line.endswith(":"):
        return True
    return word_count >= 8 and operator_count <= 2 and sentence_punctuation


def _is_command_line(stripped_line: str) -> bool:
    parts = _command_parts(stripped_line)
    if not parts:
        return False

    first = parts[0]
    rest = parts[1:]
    second = rest[0] if rest else ""
    known_command = bool(
        _SHELL_COMMAND_RE.search(stripped_line)
        or _WINDOWS_COMMAND_RE.search(stripped_line)
    )
    powershell_command = bool(_POWERSHELL_COMMAND_RE.search(stripped_line))
    executable_command = bool(_EXECUTABLE_TOKEN_RE.search(first))
    command_syntax = _has_command_syntax(stripped_line, parts)

    if len(parts) == 1:
        return powershell_command or executable_command

    if _PROSE_COMMAND_WORD_RE.match(first):
        return False

    if _PROSE_COMMAND_WORD_RE.match(second):
        return False

    if not command_syntax and any(
        _PROSE_COMMAND_WORD_RE.match(part) for part in rest[1:4]
    ):
        return False

    if powershell_command:
        return command_syntax or not any(
            _PROSE_COMMAND_WORD_RE.match(part) for part in rest[:3]
        )

    if executable_command:
        return True

    if known_command:
        return command_syntax or bool(_COMMAND_SUBCOMMAND_RE.match(second))

    return bool(_GENERIC_COMMAND_HINT_RE.search(stripped_line))


def _line_code_score(line: str) -> tuple[int, bool, bool]:
    stripped_line = line.strip()
    if not stripped_line:
        return 0, False, False

    score = 0
    looks_like_prose_line = _looks_like_prose_line(stripped_line)
    is_sql_line = _has_sql_syntax(stripped_line)
    is_command_line = _is_command_line(stripped_line)
    line_operator_count = len(_CODE_OPERATOR_RE.findall(stripped_line))

    if line.startswith(("    ", "\t")):
        score += 1
    if is_sql_line or is_command_line:
        score += 3
    if _GENERIC_COMMAND_HINT_RE.search(stripped_line) and not looks_like_prose_line:
        score += 2
    parts = _command_parts(stripped_line)
    if (
        len(parts) >= 2
        and _COMMAND_SUBCOMMAND_RE.match(parts[1])
        and not looks_like_prose_line
    ):
        score += 2
    if _SHEBANG_RE.search(stripped_line):
        score += 3
    if _DECLARATION_LINE_RE.search(stripped_line) or _IMPORT_LINE_RE.search(
        stripped_line
    ):
        score += 3
    if _METHOD_SIGNATURE_RE.search(stripped_line):
        score += 3
    if _RUBY_COMMAND_RE.search(stripped_line):
        score += 2
    if _is_dockerfile_line(stripped_line):
        score += 3
    if _MAKEFILE_LINE_RE.search(stripped_line):
        score += 2
    if _ASSIGNMENT_RE.search(stripped_line) or _VARIABLE_DECL_RE.search(stripped_line):
        score += 2
    if _STATEMENT_LINE_RE.search(stripped_line):
        score += 1
    if _SHELL_CONTROL_LINE_RE.search(stripped_line):
        score += 2
    if _CALL_LINE_RE.search(stripped_line):
        score += 2
    if _STRUCTURED_DATA_LINE_RE.search(stripped_line) and not looks_like_prose_line:
        score += 1
    if _JSON_OBJECT_LINE_RE.search(stripped_line):
        score += 4
    if _COMMENT_LINE_RE.search(stripped_line):
        score += 1
    if _BLOCK_DELIMITER_LINE_RE.search(stripped_line):
        score += 1
    if (
        not looks_like_prose_line
        and _CODE_KEYWORD_RE.search(stripped_line)
        and (line_operator_count > 0 or stripped_line.endswith(":"))
    ):
        score += 1
    if not looks_like_prose_line and line_operator_count >= 2:
        score += 1
    if not looks_like_prose_line and line_operator_count >= 4:
        score += 1

    return score, is_command_line, is_sql_line


def _looks_like_plain_text(stripped_text: str, lines: list[str]) -> bool:
    if _TEXT_CALLOUT_RE.match(stripped_text) or _TEXT_CALLOUT_PREFIX_RE.match(
        stripped_text
    ):
        return True

    if len(lines) <= 2:
        joined = " ".join(line.strip() for line in lines)
        if _TEXT_CALLOUT_RE.match(joined) or _TEXT_CALLOUT_PREFIX_RE.match(joined):
            return True
        score, is_command_line, is_sql_line = _line_code_score(joined)
        if score == 0 and not is_command_line and not is_sql_line:
            return True
        if score <= 1 and _PLAIN_PROSE_RE.search(joined):
            return True

    return False


def _is_high_confidence_single_line_code(stripped_text: str) -> bool:
    if not stripped_text:
        return False

    score, is_command_line, is_sql_line = _line_code_score(stripped_text)
    if is_command_line or is_sql_line:
        return True
    if score >= 4:
        return True
    if (
        score >= 3
        and len(stripped_text.split()) <= 6
        and (
            _CALL_LINE_RE.search(stripped_text)
            or _ASSIGNMENT_RE.search(stripped_text)
            or _DECLARATION_LINE_RE.search(stripped_text)
            or _STATEMENT_LINE_RE.search(stripped_text)
        )
    ):
        return True
    return False


def _classify_code_block(text: str) -> str:
    """Classify text chunks as code, text, or ambiguous."""
    if not isinstance(text, str):
        return _CODE_BLOCK_CLASS_TEXT

    normalized_text = (
        _STYLE_TAG_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    )
    stripped_text = normalized_text.strip()
    if not stripped_text:
        return _CODE_BLOCK_CLASS_TEXT

    if (
        _CODE_BLOCK_FENCE_RE.match(stripped_text)
        or stripped_text.count("```") >= 2
        or stripped_text.count("~~~") >= 2
    ):
        return _CODE_BLOCK_CLASS_CODE

    lines = [line for line in normalized_text.split("\n") if line.strip()]
    if _looks_like_plain_text(stripped_text, lines):
        return _CODE_BLOCK_CLASS_TEXT

    if len(lines) < 2:
        if _is_high_confidence_single_line_code(stripped_text):
            return _CODE_BLOCK_CLASS_CODE
        score, is_command_line, is_sql_line = _line_code_score(stripped_text)
        if score >= 2 or is_command_line or is_sql_line:
            return _CODE_BLOCK_CLASS_AMBIGUOUS
        return _CODE_BLOCK_CLASS_TEXT

    sql_signal_count = 0
    command_signal_count = 0
    indented_count = 0
    structured_count = 0
    bracket_or_tag_count = 0
    weak_signal_count = 0
    strong_signal_count = 0
    operator_count = 0
    text_length = 0
    prose_line_count = 0

    for line in lines:
        stripped_line = line.strip()
        if line.startswith(("    ", "\t")):
            indented_count += 1
        if _looks_like_prose_line(stripped_line):
            prose_line_count += 1

        line_score, is_command_line, is_sql_line = _line_code_score(line)
        if line_score >= 1:
            weak_signal_count += 1
        if line_score >= 2:
            strong_signal_count += 1
        if is_command_line:
            command_signal_count += 1
        if is_sql_line:
            sql_signal_count += 1
        if _STRUCTURED_DATA_LINE_RE.search(stripped_line):
            structured_count += 1
        if re.search(r"^\s*[{}\[\],]+\s*$|^\s*</?[\w:-]+", stripped_line):
            bracket_or_tag_count += 1

        operator_count += len(_CODE_OPERATOR_RE.findall(stripped_line))
        text_length += len(stripped_line)

    prose_ratio = prose_line_count / len(lines)
    if prose_ratio >= 0.5 and command_signal_count == 0 and sql_signal_count == 0:
        return _CODE_BLOCK_CLASS_TEXT

    if len(lines) >= 3 and sql_signal_count / len(lines) >= 0.6:
        return _CODE_BLOCK_CLASS_CODE

    if len(lines) >= 2 and command_signal_count / len(lines) >= 0.5:
        return _CODE_BLOCK_CLASS_CODE

    if indented_count >= 2 and strong_signal_count >= 2:
        return _CODE_BLOCK_CLASS_CODE

    operator_density = operator_count / max(text_length, 1)

    if len(lines) == 2:
        if strong_signal_count == 2:
            return _CODE_BLOCK_CLASS_CODE
        if weak_signal_count == 2 and operator_density >= 0.05:
            return _CODE_BLOCK_CLASS_CODE
        if weak_signal_count > 0:
            return _CODE_BLOCK_CLASS_AMBIGUOUS
        return _CODE_BLOCK_CLASS_TEXT

    if structured_count / len(lines) >= 0.75 and (
        bracket_or_tag_count > 0 or indented_count > 0
    ):
        return _CODE_BLOCK_CLASS_CODE

    if strong_signal_count / len(lines) >= 0.5:
        if operator_density >= 0.02 or weak_signal_count / len(lines) >= 0.8:
            return _CODE_BLOCK_CLASS_CODE
        return _CODE_BLOCK_CLASS_AMBIGUOUS

    if weak_signal_count / len(lines) >= 0.75:
        if operator_density >= 0.03:
            return _CODE_BLOCK_CLASS_CODE
        return _CODE_BLOCK_CLASS_AMBIGUOUS

    if weak_signal_count > 0 or operator_density >= 0.02:
        return _CODE_BLOCK_CLASS_AMBIGUOUS

    return _CODE_BLOCK_CLASS_TEXT


def _looks_like_code_block(text: str) -> bool:
    """Conservatively identify obvious code blocks from translated text chunks."""
    return _classify_code_block(text) == _CODE_BLOCK_CLASS_CODE


def _build_code_block_classifier_prompt(text: str) -> str:
    return (
        "Classify whether this PDF paragraph should be skipped by a translator "
        "because it is code, command-line text, configuration, logs, or a stack trace.\n"
        "Return ONLY compact JSON with this exact shape:\n"
        '{"decision":"skip|translate","confidence":0.0,'
        '"line_kinds":["code|command|config|log|text|blank"]}\n\n'
        "Rules:\n"
        "- Return skip for actual source code, shell/cmd/PowerShell commands, "
        "config files, logs, stack traces, and code-like fragments.\n"
        "- Return translate for prose, headings, Tips, Notes, warnings written as "
        "human-readable documentation, and sentences that merely mention commands.\n"
        "- Prefer translate when uncertain.\n\n"
        "Paragraph:\n"
        "<<<TEXT\n"
        f"{text}\n"
        "TEXT>>>"
    )


def _parse_code_block_classifier_response(response: str) -> tuple[str, float] | None:
    if not isinstance(response, str):
        return None

    stripped = response.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None

    decision = str(data.get("decision", "")).strip().lower()
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0

    return decision, confidence


class BaseTranslator(ABC):
    # Due to cache limitations, name should be within 20 characters.
    # cache.py: translate_engine = CharField(max_length=20)
    """translator 的基类，所有的 translator 的实现都需要继承"""

    name = "base"
    lang_map = {}

    def __init__(
        self,
        settings: SettingsModel,
        rate_limiter: BaseRateLimiter,
    ):
        """
        translator class initialization
        :param settings: runtime setting and configuration
        :param rate_limiter: LLM request rate control
        :return: None
        """
        self.ignore_cache = settings.translation.ignore_cache
        self.skip_code_blocks = settings.pdf.skip_code_blocks
        self.skip_code_blocks_llm = settings.pdf.skip_code_blocks_llm
        lang_in = self.lang_map.get(
            settings.translation.lang_in.lower(), settings.translation.lang_in
        )
        lang_out = self.lang_map.get(
            settings.translation.lang_out.lower(), settings.translation.lang_out
        )
        self.lang_in = lang_in
        self.lang_out = lang_out
        self.rate_limiter = rate_limiter

        self.cache = TranslationCache(
            self.name,
            {
                "lang_in": lang_in,
                "lang_out": lang_out,
            },
        )

        self.translate_call_count = 0
        self.translate_cache_call_count = 0

    def __del__(self):
        with contextlib.suppress(Exception):
            logger.info(
                f"{self.name} translate call count: {self.translate_call_count}"
            )
            logger.info(
                f"{self.name} translate cache call count: {self.translate_cache_call_count}",
            )

    def add_cache_impact_parameters(self, k: str, v):
        """
        Add parameters that affect the translation quality to distinguish the translation effects under different parameters.
        :param k: key
        :param v: value
        """
        self.cache.add_params(k, v)

    def should_skip_code_block(self, text: str) -> bool:
        if not self.skip_code_blocks:
            return False

        classification = _classify_code_block(text)
        if classification == _CODE_BLOCK_CLASS_CODE:
            return True
        if classification == _CODE_BLOCK_CLASS_TEXT:
            return False
        if not self.skip_code_blocks_llm:
            return False

        try:
            return self._llm_should_skip_code_block(text)
        except NotImplementedError:
            logger.debug("LLM code block classification is not supported")
        except Exception as e:
            logger.debug(f"LLM code block classification failed: {e}")
        return False

    def _llm_should_skip_code_block(self, text: str) -> bool:
        prompt = _build_code_block_classifier_prompt(text)
        response = self.llm_translate(
            prompt,
            rate_limit_params={"request_json_mode": True},
        )
        parsed_response = _parse_code_block_classifier_response(response)
        if parsed_response is None:
            return False

        decision, confidence = parsed_response
        return decision == "skip" and confidence >= _CODE_BLOCK_LLM_SKIP_CONFIDENCE

    def translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if self.should_skip_code_block(text):
            logger.debug("Skip translating detected code block")
            return text
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                logger.debug(f"try get cache failed, ignore it: {e}")
        self.rate_limiter.wait(rate_limit_params)
        translation = self.do_translate(text, rate_limit_params)
        if not (self.ignore_cache or ignore_cache):
            self.cache.set(text, translation)
        return translation

    def llm_translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if self.skip_code_blocks:
            babeldoc_text = _extract_babeldoc_text_to_translate(text)
            if babeldoc_text is not None and self.should_skip_code_block(babeldoc_text):
                logger.debug(
                    "Skip translating detected code block from BabelDOC prompt"
                )
                return babeldoc_text
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                logger.debug(f"try get cache failed, ignore it: {e}")
        self.rate_limiter.wait(rate_limit_params)
        translation = self.do_llm_translate(text, rate_limit_params)
        if not (self.ignore_cache or ignore_cache):
            self.cache.set(text, translation)
        return translation

    def do_llm_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        raise NotImplementedError

    @abstractmethod
    def do_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        logger.critical(
            f"Do not call BaseTranslator.do_translate. "
            f"Translator: {self}. "
            f"Text: {text}. ",
        )
        raise NotImplementedError

    def _remove_cot_content(self, content: str) -> str:
        """Remove text content with the thought chain from the chat response

        :param content: Non-streaming text content
        :return: Text without a thought chain
        """
        return re.sub(r"^<think>.+?</think>", "", content, count=1, flags=re.DOTALL)

    def __str__(self):
        """
        get translator's info
        """
        return f"{self.name} {self.lang_in} {self.lang_out} {self.model}"

    def get_formular_placeholder(self, placeholder_id: int):
        """
        get formular placeholder
        LLM translator use placeholder to skip the formular char
        :param placeholder_id: placeholder id
        :return formated placeholder and regex placeholder
        """
        return "{v" + str(placeholder_id) + "}", f"{{\\s*v\\s*{placeholder_id}\\s*}}"

    def get_rich_text_left_placeholder(self, placeholder_id: int):
        """
        get rich text placeholder
        :param placeholder_id: placeholder id
        :return the start label of rich text and regex start label
        """
        return (
            f"<style id='{placeholder_id}'>",
            f"<\\s*style\\s*id\\s*=\\s*'\\s*{placeholder_id}\\s*'\\s*>",
        )

    def get_rich_text_right_placeholder(self, placeholder_id: int):
        """
        get rich text placeholder
        :return the end label of rich text and regex end label
        """
        return "</style>", r"<\s*\/\s*style\s*>"

    def prompt(self, text):
        """
        concatent the prompt
        :param text: input text
        :return: the whole prompt for LLM translator
        """
        return [
            {
                "role": "user",
                "content": f"You are a professional,authentic machine translation engine.\n\n;; Treat next line as plain text input and translate it into {self.lang_out}, output translation ONLY. If translation is unnecessary (e.g. proper nouns, codes, {'{{1}}, etc. '}), return the original text. NO explanations. NO notes. Input:\n\n{text}",
            },
        ]
