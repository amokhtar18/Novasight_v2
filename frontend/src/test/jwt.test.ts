/**
 * Tests for display-only JWT decoding. These prove the parser is robust to
 * malformed input (returns null, never throws) and normalizes the roles claim.
 */

import { describe, it, expect } from "vitest";
import { decodeJwt, rolesOf } from "@/lib/jwt";

/** Build an unsigned JWT-shaped string from a claims object (header.payload.sig). */
function makeToken(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(claims)}.sig`;
}

describe("decodeJwt", () => {
  it("decodes the payload of a well-formed token", () => {
    const token = makeToken({ tenant: "acme", roles: ["platform-admin"], sub: "u1" });
    const claims = decodeJwt(token);
    expect(claims?.tenant).toBe("acme");
    expect(claims?.sub).toBe("u1");
  });

  it("returns null for malformed / empty tokens", () => {
    expect(decodeJwt(undefined)).toBeNull();
    expect(decodeJwt("")).toBeNull();
    expect(decodeJwt("not-a-jwt")).toBeNull();
    expect(decodeJwt("a.b")).not.toBeUndefined(); // 2 segments: tries to parse b
  });

  it("does not throw on non-JSON payloads", () => {
    expect(() => decodeJwt("aaa.!!!.ccc")).not.toThrow();
    expect(decodeJwt("aaa.!!!.ccc")).toBeNull();
  });
});

describe("rolesOf", () => {
  it("normalizes an array roles claim", () => {
    expect(rolesOf({ roles: ["a", "b"] })).toEqual(["a", "b"]);
  });
  it("splits a space/comma-delimited roles string", () => {
    expect(rolesOf({ roles: "a b,c" })).toEqual(["a", "b", "c"]);
  });
  it("returns [] when no roles present", () => {
    expect(rolesOf(null)).toEqual([]);
    expect(rolesOf({})).toEqual([]);
  });
});
