import axe from "axe-core";

/**
 * Run axe-core on part of the rendered page and return readable violation lines (empty = clean).
 * jsdom has no layout, so colour contrast and anything else that needs rendering is switched off
 * here; contrast is measured against the real app separately. Page-level rules (landmarks, one
 * h1, document title) are not meaningful for a rendered fragment either.
 */
export async function violations(root: Element): Promise<string[]> {
  const results = await axe.run(root, {
    resultTypes: ["violations"],
    rules: {
      "color-contrast": { enabled: false },
      region: { enabled: false },
      "landmark-one-main": { enabled: false },
      "page-has-heading-one": { enabled: false },
    },
  });
  return results.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help} -> ${v.nodes
        .slice(0, 3)
        .map((n) => n.target.join(" "))
        .join(" | ")}`,
  );
}
