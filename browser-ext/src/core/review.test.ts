import { describe, expect, test } from "vitest";

import {
  findParagraphByText,
  getAddEdit,
  getEditContext,
  getEditedLines,
  getPlainText,
  getReply,
  getReviewThreads,
  getOverleafSyncedLines,
  getThreadEdit,
  isEditCurrent,
} from "./review";

const MAIN = [
  "\\section{Results}",
  "",
  '% COMMENT id=3f9a2c1b highlight={text: "four speeds"}',
  "%   Pat <pat@example.com> (2026-11-01 10:00):",
  "%     Which speeds?",
  "We towed a cylinder at four speeds",
  "and measured the profile~\\cite{ref}.",
  "",
  "% COMMENT resolved=true",
  "%   Sam:",
  "%     Done.",
  "The wake recovers downstream.",
];

const author = { name: "Jo Doe", email: "jo@example.com" };

describe("getReviewThreads", () => {
  test("reads threads with the paragraphs they're about", () => {
    const threads = getReviewThreads(
      new Map([
        ["sec/intro.tex", "No comments here."],
        ["main.tex", MAIN.join("\n")],
      ]),
    );
    expect(threads.map((t) => t.key)).toEqual(["3f9a2c1b", "main.tex:9"]);
    expect(threads[0]).toMatchObject({
      id: "3f9a2c1b",
      path: "main.tex",
      line: 3,
      nlines: 3,
      resolved: false,
      highlight: { text: "four speeds", occ: 0 },
      anchor: {
        line: 6,
        end_line: 7,
        text: "We towed a cylinder at four speeds and measured the profile.",
      },
      messages: [
        {
          author: "Pat",
          email: "pat@example.com",
          date: "2026-11-01 10:00",
          text: "Which speeds?",
        },
      ],
    });
    expect(threads[1]).toMatchObject({
      id: null,
      resolved: true,
      highlight: null,
      anchor: { line: 12, end_line: 12 },
    });
  });
});

describe("getPlainText", () => {
  test("drops comments, commands, and braces", () => {
    expect(
      getPlainText([
        "A \\textbf{bold} claim~\\cite{x} with $u_\\infty$, % not this",
        "and 50\\% more.",
      ]),
    ).toBe("A bold claim with u_, and 50 more.");
  });
});

describe("findParagraphByText", () => {
  test("finds the paragraph sharing the most words", () => {
    const files = new Map([
      ["main.tex", MAIN.join("\n")],
      ["other.tex", "Something about towing tanks.\n"],
    ]);
    expect(
      findParagraphByText(files, "We towed a cylinder at four speeds and"),
    ).toMatchObject({ file: "main.tex", line: 6 });
    expect(findParagraphByText(files, "wake recovers")).toMatchObject({
      file: "main.tex",
      line: 12,
    });
    expect(findParagraphByText(files, "xyz")).toBeNull();
  });
});

describe("comment edits", () => {
  test("adds a thread above a paragraph, below any there", () => {
    const edit = getAddEdit(MAIN, 7, author, "How fast?", "the profile", 0);
    expect(edit.line).toBe(6);
    expect(edit.count).toBe(0);
    expect(edit.insert[0]).toMatch(
      /^% COMMENT id=[0-9a-f]{8} highlight=\{text: "the profile"\}$/,
    );
    expect(edit.insert[1]).toMatch(
      /^% {3}Jo Doe <jo@example\.com> \(\d{4}-\d\d-\d\d \d\d:\d\d\):$/,
    );
    expect(edit.insert[2]).toBe("%     How fast?");
    const lines = getEditedLines(MAIN, edit);
    expect(lines.slice(2, 5)).toEqual(MAIN.slice(2, 5));
    expect(lines[8]).toBe(MAIN[5]);
    expect(() => getAddEdit(["", ""], 1, author, "x", "", 0)).toThrow(
      "No paragraph",
    );
  });
  test("replies to, resolves, and deletes threads", () => {
    const reply = getThreadEdit(
      MAIN,
      { id: "3f9a2c1b" },
      getReply(author, "Four."),
    );
    expect(reply).toMatchObject({ line: 3, count: 3 });
    expect(reply.insert.slice(0, 3)).toEqual(MAIN.slice(2, 5));
    expect(reply.insert[4]).toBe("%     Four.");
    // Found by any of its lines when it has no ID, which it then gets
    const resolve = getThreadEdit(MAIN, { line: 10 }, (t) => ({
      ...t,
      resolved: false,
    }));
    expect(resolve).toMatchObject({ line: 9, count: 3 });
    expect(resolve.insert[0]).toMatch(/^% COMMENT id=[0-9a-f]{8}$/);
    const deleted = getThreadEdit(MAIN, { id: "3f9a2c1b" }, null);
    expect(getEditedLines(MAIN, deleted)).toEqual([
      ...MAIN.slice(0, 2),
      ...MAIN.slice(5),
    ]);
    expect(() => getThreadEdit(MAIN, { id: "00000000" }, null)).toThrow(
      "no longer in the source",
    );
  });
});

describe("isEditCurrent", () => {
  test("checks the lines an edit replaces and those either side", () => {
    const check = (
      lines: string[],
      line: number,
      count: number,
      now: string[],
    ) =>
      isEditCurrent((n) => now[n - 1], now.length, {
        line,
        ...getEditContext(lines, { line, count, insert: [] }),
      });
    // A thread inserted above a paragraph, with nothing to replace
    expect(getEditContext(MAIN, { line: 6, count: 0, insert: [] })).toEqual({
      before: "%     Which speeds?",
      expected: [],
      after: "We towed a cylinder at four speeds",
    });
    expect(check(MAIN, 6, 0, MAIN)).toBe(true);
    // A line typed just above or below the insertion point
    expect(
      check(MAIN, 6, 0, [...MAIN.slice(0, 5), "New", ...MAIN.slice(5)]),
    ).toBe(false);
    expect(
      check(MAIN, 6, 0, [...MAIN.slice(0, 5), "Edit", ...MAIN.slice(6)]),
    ).toBe(false);
    // The same thread put in by another refresh or tab first
    const inserted = getEditedLines(MAIN, {
      line: 6,
      count: 0,
      insert: ["% COMMENT overleaf=abc", "%   Pat:", "%     Hi."],
    });
    expect(check(MAIN, 6, 0, inserted)).toBe(false);
    // Lines replaced, changed, and edits elsewhere left alone
    expect(check(MAIN, 3, 3, MAIN)).toBe(true);
    expect(
      check(
        MAIN,
        3,
        3,
        MAIN.map((l, i) => (i === 3 ? "%   Sam:" : l)),
      ),
    ).toBe(false);
    expect(check(MAIN, 3, 3, [...MAIN.slice(0, 8), "More"])).toBe(true);
    // At either end, where there's no line beyond to check
    expect(check(MAIN, 1, 0, MAIN)).toBe(true);
    expect(check(MAIN, 1, 0, ["", ...MAIN])).toBe(false);
    expect(check(MAIN, MAIN.length + 1, 0, MAIN)).toBe(true);
    expect(check(MAIN, MAIN.length + 1, 0, [...MAIN, "End"])).toBe(false);
    expect(check(MAIN, MAIN.length - 1, 2, MAIN.slice(0, -1))).toBe(false);
  });
});

describe("getOverleafSyncedLines", () => {
  const text = [
    "\\section{Results}",
    "",
    "We towed a cylinder at four speeds",
    "and measured the profile at four speeds.",
    "",
    "The wake recovers downstream.",
  ];
  const offsetOf = (needle: string, from = 0) =>
    text.join("\n").indexOf(needle, from);
  const pat = { first_name: "Pat", last_name: "Lee", email: "pat@x.org" };
  test("brings new Overleaf threads into the source", () => {
    const { lines, synced } = getOverleafSyncedLines(
      text,
      [
        {
          thread: "a1",
          text: "four speeds",
          offset: offsetOf("four speeds", offsetOf("profile")),
        },
        { thread: "b2", text: "wake", offset: offsetOf("wake") },
        // A thread with no messages yet is left until it has one
        { thread: "c3", text: "towed", offset: offsetOf("towed") },
      ],
      {
        a1: {
          messages: [
            {
              content: "Which\nspeeds?",
              timestamp: Date.UTC(2026, 10, 1, 10, 0),
              user: pat,
            },
          ],
        },
        b2: { messages: [{ content: "Nice." }], resolved: true },
        c3: { messages: [] },
      },
      {},
      "Jo Doe",
    );
    expect(lines[2]).toMatch(
      /^% COMMENT id=[0-9a-f]{8} highlight=\{text: "four speeds", occ: 1\} overleaf=a1$/,
    );
    expect(lines.slice(3, 5)).toEqual([
      "%   Pat Lee <pat@x.org> (2026-11-01 10:00):",
      "%     Which speeds?",
    ]);
    expect(lines.slice(5, 7)).toEqual(text.slice(2, 4));
    expect(lines[8]).toMatch(
      /^% COMMENT id=[0-9a-f]{8} resolved=true highlight=\{text: "wake"\} overleaf=b2$/,
    );
    expect(lines.slice(9, 12)).toEqual([
      "%   Someone on Overleaf:",
      "%     Nice.",
      text[5],
    ]);
    expect(synced).toEqual({
      a1: { resolved: false, messages: 1 },
      b2: { resolved: true, messages: 1 },
    });
  });
  test("keeps threads in step with Overleaf", () => {
    const source = [
      "% COMMENT id=11111111 overleaf=a1",
      "%   Pat:",
      "%     Why?",
      "First paragraph.",
      "",
      "% COMMENT id=22222222 resolved=true overleaf=b2",
      "%   Pat:",
      "%     Fix this.",
      "Second paragraph.",
      "",
      "% COMMENT id=33333333 overleaf=c3",
      "%   Pat:",
      "%     Gone?",
      "Third paragraph.",
    ];
    const { lines, pushes, synced } = getOverleafSyncedLines(
      source,
      [],
      {
        // A reply on Overleaf
        a1: {
          messages: [{ content: "Why?" }, { content: "Because.", user: pat }],
        },
        // Resolved in the source only, so it stays resolved
        b2: { messages: [{ content: "Fix this." }] },
      },
      {
        a1: { resolved: false, messages: 1 },
        b2: { resolved: false, messages: 1 },
        // Deleted on Overleaf
        c3: { resolved: false, messages: 1 },
      },
      "Jo Doe",
    );
    expect(lines).toEqual([
      ...source.slice(0, 3),
      "%   Pat Lee <pat@x.org>:",
      "%     Because.",
      ...source.slice(3, 10),
      "Third paragraph.",
    ]);
    expect(pushes).toEqual([{ thread: "b2", replies: [], resolved: true }]);
    expect(synced).toEqual({
      a1: { resolved: false, messages: 2 },
      b2: { resolved: true, messages: 1 },
    });
    // Reopened on Overleaf since it was resolved in step
    expect(
      getOverleafSyncedLines(
        source.slice(5, 9),
        [],
        { b2: { messages: [{ content: "Fix this." }], resolved: false } },
        { b2: { resolved: true, messages: 1 } },
        "Jo Doe",
      ).lines[0],
    ).toBe("% COMMENT id=22222222 overleaf=b2");
    // Replied to on both sides since they were in step
    const both = getOverleafSyncedLines(
      [
        "% COMMENT id=44444444 overleaf=d4",
        "%   Pat:",
        "%     Why?",
        "%   Jo Doe:",
        "%     Because.",
        "%   Sam:",
        "%     Agreed.",
        "Text.",
      ],
      [],
      {
        d4: {
          messages: [
            { content: "Why?" },
            { content: "Any news?", user: { first_name: "Pat" } },
          ],
        },
      },
      { d4: { resolved: false, messages: 1 } },
      "Jo Doe",
    );
    expect(both.lines.slice(7, 9)).toEqual(["%   Pat:", "%     Any news?"]);
    expect(both.pushes).toEqual([
      { thread: "d4", replies: ["Because.", "Sam: Agreed."] },
    ]);
    expect(both.synced).toEqual({ d4: { resolved: false, messages: 4 } });
    // Deleted from the source after being in step, so not brought back
    const deleted = getOverleafSyncedLines(
      ["Text."],
      [{ thread: "e5", text: "Text", offset: 0 }],
      { e5: { messages: [{ content: "Hm." }] } },
      { e5: { resolved: false, messages: 1 } },
      "Jo Doe",
    );
    expect(deleted.lines).toEqual(["Text."]);
    expect(deleted.pushes).toEqual([
      { thread: "e5", replies: [], deleted: true },
    ]);
    expect(deleted.synced).toEqual({});
    // Posted to Overleaf from the source, so linked, with the rest sent
    const posted = getOverleafSyncedLines(
      [
        "% COMMENT id=55555555 resolved=true",
        "%   Sam:",
        "%     Check this.",
        "%   Jo Doe:",
        "%     Checked.",
        "Text here.",
      ],
      [{ thread: "f6", text: "Text", offset: 90 }],
      { f6: { messages: [{ content: "Sam: Check this." }] } },
      {},
      "Jo Doe",
    );
    expect(posted.lines[0]).toBe(
      "% COMMENT id=55555555 resolved=true overleaf=f6",
    );
    expect(posted.lines.length).toBe(6);
    expect(posted.pushes).toEqual([
      { thread: "f6", replies: ["Checked."], resolved: true },
    ]);
    expect(posted.synced).toEqual({ f6: { resolved: true, messages: 2 } });
  });
});
