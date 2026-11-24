export const photoLicenses: Record<string, string> = {
  "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
  "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
  "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
  "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
  "PD-textlogo": "https://commons.wikimedia.org/wiki/Template:PD-textlogo",
  CC0: "https://creativecommons.org/publicdomain/zero/1.0/",
};
export type PhotoAsset = {
  image: string;
  author: string;
  source: string;
  license: string;
  changes: string;
};
export type PhotoRef = "zywoo-chicago-2019" | PhotoAsset | null;
export function resolvePortrait(ref?: PhotoRef): PhotoAsset | null {
  if (ref !== "zywoo-chicago-2019") return ref || null;
  return {
    image:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/IEM_Chicago_Final_Edits-9731_ZywOo_%2848353577846%29_%28cropped%29.jpg/250px-IEM_Chicago_Final_Edits-9731_ZywOo_%2848353577846%29_%28cropped%29.jpg",
    author: "Esports Kingdom",
    source:
      "https://commons.wikimedia.org/wiki/File:IEM_Chicago_Final_Edits-9731_ZywOo_(48353577846)_(cropped).jpg",
    license: "CC BY 2.0",
    changes: "кадрирование",
  };
}
