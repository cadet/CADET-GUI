// Parses the LaTeX subset units are written in (^ _ {} \mathrm \cdot \frac)
// into [{ text } | { sup: nodes } | { sub: nodes }]. \frac is flattened to
// "a/b" (denominator parenthesised when compound) so a unit stays on one line.
function parseUnit(src) {
  const symbols = { cdot: "·", times: "×", ",": " ", " ": " " };
  const textCommands = ["mathrm", "text", "textrm"];
  let i = 0;

  const append = (out, nodes) => {
    for (const node of nodes) {
      const last = out[out.length - 1];
      if (node.text !== undefined && last && last.text !== undefined) last.text += node.text;
      else out.push(node);
    }
  };
  const hasTopLevel = (nodes, chars) =>
    nodes.some((n) => n.text !== undefined && [...chars].some((c) => n.text.includes(c)));
  const paren = (nodes, needed) =>
    needed ? [{ text: "(" }, ...nodes, { text: ")" }] : nodes;

  function parseArg() {
    while (src[i] === " ") i++;
    if (i >= src.length) return [];
    if (src[i] === "{") {
      i++;
      return parseSeq(true);
    }
    const out = [];
    if (src[i] === "\\") {
      parseCommand(out);
    } else {
      append(out, [{ text: src[i] }]);
      i++;
    }
    return out;
  }

  function parseCommand(out) {
    i++;
    const letters = /^[A-Za-z]+/.exec(src.slice(i));
    const name = letters ? letters[0] : src.charAt(i);
    i += name.length;
    if (letters) while (src[i] === " ") i++;
    if (textCommands.includes(name)) {
      append(out, parseArg());
    } else if (name === "frac") {
      const num = parseArg();
      const den = parseArg();
      append(out, paren(num, hasTopLevel(num, "/")));
      append(out, [{ text: "/" }]);
      append(out, paren(den, hasTopLevel(den, "·×/")));
    } else if (name in symbols) {
      append(out, [{ text: symbols[name] }]);
    } else {
      append(out, [{ text: letters ? `\\${name}` : name || "\\" }]);
    }
  }

  function parseSeq(untilBrace) {
    const out = [];
    while (i < src.length) {
      const ch = src[i];
      if (ch === "}" && untilBrace) {
        i++;
        return out;
      }
      if (ch === "{") {
        i++;
        append(out, parseSeq(true));
      } else if (ch === "\\") {
        parseCommand(out);
      } else if (ch === "^" || ch === "_") {
        i++;
        out.push(ch === "^" ? { sup: parseArg() } : { sub: parseArg() });
      } else {
        append(out, [{ text: ch }]);
        i++;
      }
    }
    return out;
  }

  return parseSeq(false);
}
