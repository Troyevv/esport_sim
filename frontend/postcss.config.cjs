// Keep the approved styles local to the screens using the R5.7.1 component tree.
module.exports = {
  plugins: [
    {
      postcssPlugin: "approved-interface",
      Once(root, { result, AtRule }) {
        const file = result.opts.from?.replaceAll("\\", "/");
        if (!file?.includes("/src/")) return;
        if (!file.includes("/src/approved/")) {
          // Preserve the relative order of the existing game styles. Approved components
          // can then opt out of their inherited element and layout rules as one layer.
          const layer = new AtRule({ name: "layer", params: "game" });
          layer.append(root.nodes.slice());
          root.append(layer);
          return;
        }
        root.walkRules((rule) => {
          if (
            rule.parent.type === "atrule" &&
            rule.parent.name.endsWith("keyframes")
          )
            return;
          rule.selectors = rule.selectors.map((selector) =>
            /^(?:body|:root)\b/.test(selector)
              ? selector.replace(/^(?:body|:root)/, ".r571.r571")
              : ".r571.r571 " + selector,
          );
        });
        root.walkDecls((decl) => {
          decl.value = decl.value.replaceAll(
            "/assets/interface/fonts/",
            "/interface/fonts/",
          );
        });
      },
    },
  ],
};
