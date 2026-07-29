// How the freeform Japanese in `name`/`address`/`hours`/`holidays` is broken
// into lines for the detail panel. Kept here (pure, no React) rather than in
// panel/ so the rules can be pinned by unit tests - the source text is written
// by hand upstream and every new run can introduce a shape nobody has seen.
//
// The pipeline stores the source text as-is apart from turning `<br>` into a
// space, so all line-breaking policy lives on this side. Nothing here edits the
// data; a hard-to-parse string just comes back as a single line.

// A parenthetical is captured as its own chunk, so it is atomic: a space or a
// comma inside it never breaks a line. `[^）)]*` means an unclosed bracket
// simply doesn't match, and that text survives untouched instead of being
// mangled.
const PARENTHETICAL = /([（(][^）)]*[）)])/;

// Break at these in the surrounding text. Whitespace is in the set because
// that is how the source's `<br>`s arrive (see pipeline/app/description.py);
// commas are dropped at the break rather than left stranded at a line start.
const SEPARATORS = /[\s、,，]/u;
const COMMAS = /[、,，]/u;

// Anything that is not a letter, digit or whitespace. Kana and kanji are
// letters, so this is punctuation and symbols only - `\w` would be no use
// here, being ASCII-only in JS.
const SYMBOL = /[^\p{L}\p{N}\s]/u;

// A parenthetical shorter than this reads as a tight qualifier on the text it
// follows - `（L.O.16:30）`, `(土日祝は15:00)` - and looks wrong pushed onto its
// own line. Longer ones are their own clause. Measured on the bracket contents.
const MIN_INSIDE_FOR_BREAK = 10;

/** True when a closing bracket followed by `next` should *not* break the line:
 *  a symbol other than a comma joins the parenthetical to what comes after it
 *  (`(不定休)・日`), while a comma, a letter, a digit or whitespace all break. */
function joinsToNext(next: string): boolean {
  return next !== '' && !COMMAS.test(next) && SYMBOL.test(next);
}

type Options = {
  /** Whether whitespace starts a new line. True for the panel's fields, where
   *  a space stands in for a source `<br>`; false for the location name, whose
   *  spaces are ordinary spaces (`三交イン 沼津駅前`) and must stay inline. */
  breakOnWhitespace?: boolean;
};

export function toDisplayLines(text: string, { breakOnWhitespace = true }: Options = {}): string[] {
  const separator = breakOnWhitespace ? SEPARATORS : COMMAS;
  const chunks = text.split(PARENTHETICAL);
  const lines: string[] = [];
  let current = '';
  // a break owed by a separator that ended the previous chunk - held over so a
  // short parenthetical right after it still starts its own line
  let pending = false;

  const flush = () => {
    const line = current.trim();
    if (line) lines.push(line);
    current = '';
  };

  chunks.forEach((chunk, i) => {
    if (i % 2 === 1) {
      const inside = chunk.slice(1, -1);
      if (pending || inside.length >= MIN_INSIDE_FOR_BREAK) flush();
      pending = false;
      current += chunk;
      if (!joinsToNext(chunks[i + 1]?.[0] ?? '')) flush();
      return;
    }

    const parts = chunk
      .split(separator)
      .map((part) => part.trim())
      .filter(Boolean);
    if (parts.length === 0) {
      // separators only (e.g. the `、` between two parentheticals): remember the
      // break, there is no text to emit
      pending = pending || chunk !== '';
      return;
    }
    if ((pending || separator.test(chunk[0])) && current) flush();
    current += parts[0];
    parts.slice(1).forEach((part) => {
      flush();
      current = part;
    });
    pending = separator.test(chunk[chunk.length - 1]);
  });

  flush();
  return lines;
}
