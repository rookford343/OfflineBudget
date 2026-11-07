import { test, expect } from "bun:test";
import { isUnreachable } from "./connection";

test("no response means unreachable", () => {
  expect(isUnreachable({ isAxiosError: true, response: undefined })).toBe(true);
});
test("any HTTP status means reachable", () => {
  expect(isUnreachable({ isAxiosError: true, response: { status: 500 } })).toBe(false);
  expect(isUnreachable({ isAxiosError: true, response: { status: 401 } })).toBe(false);
});
test("non-axios errors are not unreachable", () => {
  expect(isUnreachable(new Error("boom"))).toBe(false);
});
test("an axios timeout with no response is unreachable", () => {
  expect(isUnreachable({ isAxiosError: true, code: "ECONNABORTED", response: undefined })).toBe(true);
  expect(isUnreachable({ isAxiosError: true, code: "ETIMEDOUT", response: undefined })).toBe(true);
});
