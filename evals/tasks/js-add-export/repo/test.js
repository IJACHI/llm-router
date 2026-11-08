const assert = require("assert");
const { reverse, capitalize } = require("./utils");
assert.strictEqual(reverse("abc"), "cba");
assert.strictEqual(capitalize("hello world"), "Hello world");
assert.strictEqual(capitalize(""), "");
console.log("ok");
