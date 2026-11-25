/* Orca AI Assistant v3.0 — Code-Fence-First Markdown Renderer */

function escapeHtml(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function _mdLabel(key, fallback) {
  if (typeof window !== "undefined" && typeof window.t === "function") {
    return window.t(key);
  }
  return fallback;
}

function copyTextFallback(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  ta.style.top = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
  } catch (_e) {
    // ignore
  }
  document.body.removeChild(ta);
}

function copyCodeBlock(btn) {
  if (!btn) return;
  const wrap = btn.closest(".md-code-block");
  const codeEl = wrap ? wrap.querySelector("pre code") : null;
  const raw = codeEl ? codeEl.textContent || "" : "";
  const finish = function () {
    const orig = btn.getAttribute("data-orig-label") || _mdLabel("btn_copy_code", "Copy");
    btn.setAttribute("data-orig-label", orig);
    btn.textContent = _mdLabel("btn_copied", "Copied");
    if (typeof window.showToast === "function") {
      window.showToast(_mdLabel("toast_copied", "Copied"));
    }
    clearTimeout(btn._copyTimer);
    btn._copyTimer = setTimeout(function () {
      btn.textContent = _mdLabel("btn_copy_code", orig);
    }, 1600);
  };

  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    navigator.clipboard.writeText(raw).then(finish, function () {
      copyTextFallback(raw);
      finish();
    });
  } else {
    copyTextFallback(raw);
    finish();
  }
}

function _renderInlineMarkdown(rawText) {
  const inlineCodes = [];
  let text = String(rawText || "").replace(/`([^`\n]+)`/g, function (_m, code) {
    const idx = inlineCodes.length;
    inlineCodes.push("<code>" + escapeHtml(code) + "</code>");
    return "\u0000IC_" + idx + "\u0000";
  });

  text = escapeHtml(text);

  // Safe links: [label](https://...) or [label](http://...)
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function (_m, label, url) {
    return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + "</a>";
  });

  // Bold + italic ***text***
  text = text.replace(/\*\*\*([^*\n]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  // Bold **text**
  text = text.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  // Strikethrough ~~text~~
  text = text.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  // Italic *text* (avoid matching lone asterisks or spaces)
  text = text.replace(/(^|[^\w*])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?!\*)/g, "$1<em>$2</em>");

  // Restore inline code tokens
  text = text.replace(/\u0000IC_(\d+)\u0000/g, function (_m, idx) {
    return inlineCodes[Number(idx)] || "";
  });

  return text;
}

function _isTableSeparator(line) {
  const trimmed = line.trim();
  if (!trimmed.includes("|") && !trimmed.includes("-")) return false;
  const cleaned = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  const parts = cleaned.split("|");
  if (parts.length < 2) return false;
  return parts.every(function (cell) {
    return /^\s*:?-{2,}:?\s*$/.test(cell);
  });
}

function _splitTableCells(line) {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map(function (c) {
    return c.trim();
  });
}

function _parseTableAlignments(sepLine) {
  return _splitTableCells(sepLine).map(function (cell) {
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    return "left";
  });
}

function _matchListLine(line) {
  const u = line.match(/^(\s*)[-*+•]\s+(.*)$/);
  if (u) {
    return { indent: u[1].replace(/\t/g, "  ").length, type: "ul", content: u[2] };
  }
  const o = line.match(/^(\s*)\d+[.)]\s+(.*)$/);
  if (o) {
    return { indent: o[1].replace(/\t/g, "  ").length, type: "ol", content: o[2] };
  }
  return null;
}

function _buildCodeBlockHtml(lang, code) {
  const safeLang = escapeHtml((lang || "text").trim() || "text");
  const safeCode = escapeHtml(String(code || "").replace(/\n$/, ""));
  const copyLabel = escapeHtml(_mdLabel("btn_copy_code", "📋 Copy"));
  return (
    '<div class="md-code-block">' +
    '<div class="md-code-head">' +
    "<span>" + safeLang + "</span>" +
    '<button type="button" class="md-copy-btn" onclick="copyCodeBlock(this)">' + copyLabel + "</button>" +
    "</div>" +
    "<pre><code>" + safeCode + "</code></pre>" +
    "</div>"
  );
}

function renderMarkdown(md) {
  let src = String(md == null ? "" : md).replace(/\r\n?/g, "\n");

  // 1. Strip completed ```orca-settings / ```orca_settings blocks (rendered as Apply cards)
  src = src.replace(/```(?:orca-settings|orca_settings)\b[\s\S]*?```/gi, "");

  // 2. Replace incomplete streaming ```orca-settings block with subtle badge
  let hasPreparingSettings = false;
  src = src.replace(/```(?:orca-settings|orca_settings)\b[\s\S]*$/i, function () {
    hasPreparingSettings = true;
    return "\n\u0000PREPARING_SETTINGS\u0000\n";
  });

  // 3. Code-fence-first extraction: protect all fenced code blocks before any markdown parsing
  const codeBlocks = [];
  src = src.replace(/```([a-zA-Z0-9_+#.-]*)[ \t]*\n([\s\S]*?)```/g, function (_m, lang, code) {
    const idx = codeBlocks.length;
    codeBlocks.push(_buildCodeBlockHtml(lang, code));
    return "\n\u0000CODEBLOCK_" + idx + "\u0000\n";
  });

  // Also protect an unclosed fenced code block while streaming
  src = src.replace(/```([a-zA-Z0-9_+#.-]*)[ \t]*\n([\s\S]*)$/g, function (_m, lang, code) {
    const idx = codeBlocks.length;
    codeBlocks.push(_buildCodeBlockHtml(lang, code));
    return "\n\u0000CODEBLOCK_" + idx + "\u0000\n";
  });

  // 4. Line-by-line block parser
  const lines = src.split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // Code block placeholder
    const cbMatch = trimmed.match(/^\u0000CODEBLOCK_(\d+)\u0000$/);
    if (cbMatch) {
      out.push(codeBlocks[Number(cbMatch[1])] || "");
      i++;
      continue;
    }

    // Streaming orca-settings badge placeholder
    if (trimmed === "\u0000PREPARING_SETTINGS\u0000") {
      out.push('<div class="md-preparing-badge">' + escapeHtml(_mdLabel("preparing_settings", "⚙️ Preparing settings...")) + "</div>");
      i++;
      continue;
    }

    // Headings (# .. ####)
    const hMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (hMatch) {
      const level = hMatch[1].length;
      out.push("<h" + level + ">" + _renderInlineMarkdown(hMatch[2]) + "</h" + level + ">");
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(?:---+|\*\*\*+|___+)$/.test(trimmed)) {
      out.push("<hr/>");
      i++;
      continue;
    }

    // Blockquote
    if (/^>\s?/.test(trimmed)) {
      const qLines = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        qLines.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      out.push("<blockquote>" + qLines.map(_renderInlineMarkdown).join("<br/>") + "</blockquote>");
      continue;
    }

    // GFM Table
    if (trimmed.includes("|") && i + 1 < lines.length && _isTableSeparator(lines[i + 1])) {
      const headers = _splitTableCells(line);
      const aligns = _parseTableAlignments(lines[i + 1]);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        rows.push(_splitTableCells(lines[i]));
        i++;
      }
      let tbl = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
      headers.forEach(function (h, idx) {
        const align = aligns[idx] || "left";
        tbl += '<th style="text-align:' + align + '">' + _renderInlineMarkdown(h) + "</th>";
      });
      tbl += "</tr></thead><tbody>";
      rows.forEach(function (r) {
        tbl += "<tr>";
        for (let c = 0; c < headers.length; c++) {
          const align = aligns[c] || "left";
          tbl += '<td style="text-align:' + align + '">' + _renderInlineMarkdown(r[c] || "") + "</td>";
        }
        tbl += "</tr>";
      });
      tbl += "</tbody></table></div>";
      out.push(tbl);
      continue;
    }

    // Nested unordered / ordered lists
    const firstList = _matchListLine(line);
    if (firstList) {
      const stack = [];
      let listHtml = "";
      while (i < lines.length) {
        const li = _matchListLine(lines[i]);
        if (!li) break;

        while (stack.length > 0 && li.indent < stack[stack.length - 1].indent) {
          const popped = stack.pop();
          listHtml += "</li></" + popped.type + ">";
        }

        if (stack.length === 0 || li.indent > stack[stack.length - 1].indent) {
          listHtml += "<" + li.type + "><li>" + _renderInlineMarkdown(li.content);
          stack.push({ indent: li.indent, type: li.type });
        } else if (stack[stack.length - 1].type !== li.type) {
          const prev = stack.pop();
          listHtml += "</li></" + prev.type + "><" + li.type + "><li>" + _renderInlineMarkdown(li.content);
          stack.push({ indent: li.indent, type: li.type });
        } else {
          listHtml += "</li><li>" + _renderInlineMarkdown(li.content);
        }
        i++;
      }
      while (stack.length > 0) {
        const popped = stack.pop();
        listHtml += "</li></" + popped.type + ">";
      }
      out.push(listHtml);
      continue;
    }

    // Paragraph (collect until blank line or next block construct)
    const pLines = [];
    while (i < lines.length) {
      const cur = lines[i];
      const curTrim = cur.trim();
      if (!curTrim) break;
      if (/^\u0000(?:CODEBLOCK_\d+|PREPARING_SETTINGS)\u0000$/.test(curTrim)) break;
      if (/^#{1,4}\s+/.test(curTrim)) break;
      if (/^(?:---+|\*\*\*+|___+)$/.test(curTrim)) break;
      if (/^>\s?/.test(curTrim)) break;
      if (_matchListLine(cur)) break;
      if (curTrim.includes("|") && i + 1 < lines.length && _isTableSeparator(lines[i + 1])) break;
      pLines.push(_renderInlineMarkdown(cur));
      i++;
    }
    if (pLines.length) {
      out.push("<p>" + pLines.join("<br/>") + "</p>");
    }
  }

  let result = out.join("");
  if (hasPreparingSettings && !result.includes("md-preparing-badge")) {
    result += '<div class="md-preparing-badge">' + escapeHtml(_mdLabel("preparing_settings", "⚙️ Preparing settings...")) + "</div>";
  }
  return result;
}
