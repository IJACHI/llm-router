const assert = require("assert");
const { cartTotal } = require("./cart");
assert.strictEqual(cartTotal([{ price: 2, qty: 1 }, { price: 3, qty: 2 }]), 8);
assert.strictEqual(cartTotal([]), 0);
console.log("ok");
