import { describe, expect, test } from "vitest";

import {
  findParagraphByText,
  getAddEdit,
  getEditedLines,
  getPlainText,
  getReply,
  getReviewThreads,
  getThreadEdit,
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
