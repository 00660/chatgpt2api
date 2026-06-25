const legacyPolyfillsScript = `
(function () {
  if (typeof window.globalThis === "undefined") {
    window.globalThis = window;
  }

  if (!Array.prototype.at) {
    Object.defineProperty(Array.prototype, "at", {
      value: function (index) {
        var length = this.length >>> 0;
        var relativeIndex = Math.trunc ? Math.trunc(index) : index < 0 ? Math.ceil(index) : Math.floor(index);
        var k = relativeIndex >= 0 ? relativeIndex : length + relativeIndex;
        return k < 0 || k >= length ? undefined : this[k];
      },
      configurable: true,
      writable: true
    });
  }

  if (!Array.prototype.flat) {
    Object.defineProperty(Array.prototype, "flat", {
      value: function (depth) {
        var result = [];
        var maxDepth = depth === undefined ? 1 : Number(depth) || 0;
        var flatten = function (items, currentDepth) {
          for (var i = 0; i < items.length; i += 1) {
            if (Array.isArray(items[i]) && currentDepth < maxDepth) {
              flatten(items[i], currentDepth + 1);
            } else {
              result.push(items[i]);
            }
          }
        };
        flatten(this, 0);
        return result;
      },
      configurable: true,
      writable: true
    });
  }

  if (!Array.prototype.flatMap) {
    Object.defineProperty(Array.prototype, "flatMap", {
      value: function (callback, thisArg) {
        return Array.prototype.map.call(this, callback, thisArg).flat();
      },
      configurable: true,
      writable: true
    });
  }

  if (window.Promise && !Promise.allSettled) {
    Promise.allSettled = function (items) {
      return Promise.all(Array.prototype.map.call(items, function (item) {
        return Promise.resolve(item).then(function (value) {
          return { status: "fulfilled", value: value };
        }, function (reason) {
          return { status: "rejected", reason: reason };
        });
      }));
    };
  }
})();
`;

export function LegacyPolyfills() {
  return <script dangerouslySetInnerHTML={{ __html: legacyPolyfillsScript }} />;
}
