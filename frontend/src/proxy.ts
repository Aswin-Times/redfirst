import { NextResponse, type NextRequest } from "next/server";

import { isAllowedHost, parseAllowedHosts } from "@/lib/hosts";

const allowedHosts = parseAllowedHosts(process.env.REDFIRST_ALLOWED_HOSTS);

// Runs before rewrites, so it also guards the /api/* proxy to the backend.
export function proxy(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"), allowedHosts)) {
    return new NextResponse("Invalid Host header", { status: 400 });
  }
  return NextResponse.next();
}
