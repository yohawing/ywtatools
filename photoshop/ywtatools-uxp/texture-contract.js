/** 3DCGテクスチャのレイヤー名・出力名contract。 */

const TEXTURE_MAPS = Object.freeze([
    {
        id: "base_color",
        groupName: "BaseColor",
        suffix: "BaseColor",
        aliases: ["basecolor", "base color", "albedo", "diffuse"],
    },
    {
        id: "normal",
        groupName: "Normal",
        suffix: "Normal",
        aliases: ["normal", "normalmap", "normal map"],
    },
    {
        id: "roughness",
        groupName: "Roughness",
        suffix: "Roughness",
        aliases: ["roughness", "rough"],
    },
    {
        id: "metallic",
        groupName: "Metallic",
        suffix: "Metallic",
        aliases: ["metallic", "metalness", "metal"],
    },
    {
        id: "ambient_occlusion",
        groupName: "AO",
        suffix: "AO",
        aliases: ["ao", "ambientocclusion", "ambient occlusion", "occlusion"],
    },
    {
        id: "emissive",
        groupName: "Emissive",
        suffix: "Emissive",
        aliases: ["emissive", "emission"],
    },
    {
        id: "opacity",
        groupName: "Opacity",
        suffix: "Opacity",
        aliases: ["opacity", "alpha", "transparency"],
    },
    {
        id: "height",
        groupName: "Height",
        suffix: "Height",
        aliases: ["height", "displacement", "bump"],
    },
    {
        id: "mask",
        groupName: "Mask",
        suffix: "Mask",
        aliases: ["mask", "masks", "masktexture", "mask texture"],
    },
]);

/** 大文字小文字や区切り文字を無視できる比較名へ変換する。 */
function normalizeGroupName(name) {
    return String(name ?? "")
        .trim()
        .toLowerCase()
        .replace(/[\s_-]+/g, "");
}

/** PSD/PSBの拡張子を除いた安全な出力ベース名を返す。 */
function sanitizeBaseName(name) {
    const withoutExtension = String(name ?? "").replace(/\.(psd|psb)$/i, "");
    const sanitized = withoutExtension
        .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
        .replace(/[. ]+$/g, "")
        .trim();
    return sanitized || "texture";
}

/** トップレベルグループから既知のテクスチャ用途を検出する。 */
function detectTextureGroups(groups) {
    const matches = [];
    const usedGroupIndices = new Set();

    for (const textureMap of TEXTURE_MAPS) {
        const aliases = new Set(textureMap.aliases.map(normalizeGroupName));
        const sourceIndex = groups.findIndex(
            (group, index) =>
                !usedGroupIndices.has(index) && aliases.has(normalizeGroupName(group.name)),
        );
        if (sourceIndex === -1) {
            continue;
        }
        usedGroupIndices.add(sourceIndex);
        matches.push({ ...textureMap, sourceIndex, sourceName: groups[sourceIndex].name });
    }
    return matches;
}

/** 現在のPSDから生成するPNG一覧を返す。 */
function buildExportPlan(documentName, groups) {
    const baseName = sanitizeBaseName(documentName);
    return detectTextureGroups(groups).map((match) => ({
        ...match,
        fileName: `${baseName}_${match.suffix}.png`,
    }));
}

module.exports = {
    TEXTURE_MAPS,
    buildExportPlan,
    detectTextureGroups,
    normalizeGroupName,
    sanitizeBaseName,
};

