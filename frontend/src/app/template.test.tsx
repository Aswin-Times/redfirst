import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import Template from "@/app/template";

afterEach(cleanup);

it("wraps the page in the fade-in container without changing its content", () => {
  render(<Template><p>page body</p></Template>);
  expect(screen.getByText("page body").parentElement?.className).toBe("page-in");
});
