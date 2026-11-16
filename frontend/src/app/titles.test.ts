import { describe, expect, it } from "vitest";

import { metadata as dashboard } from "@/app/page";

describe("page metadata", () => {
  it("gives the dashboard its full title (the layout template skips a page in its own segment)", () => {
    expect(dashboard.title).toEqual({ absolute: "Dashboard · REDFIRST" });
  });
});
