/** 出力フォルダの永続トークンを管理する。 */

const OUTPUT_FOLDER_TOKEN_KEY = "ywta.textureGenerator.outputFolderToken";

/** 選択したフォルダを次回セッションで復元できるよう保存する。 */
async function saveOutputFolder(fileSystem, keyValueStore, folder) {
    if (!folder?.isFolder) {
        throw new Error("出力先にはフォルダを指定してください。");
    }
    const token = await fileSystem.createPersistentToken(folder);
    keyValueStore.setItem(OUTPUT_FOLDER_TOKEN_KEY, token);
    return folder;
}

/** 保存済みトークンから出力フォルダを復元する。 */
async function restoreOutputFolder(fileSystem, keyValueStore) {
    const token = keyValueStore.getItem(OUTPUT_FOLDER_TOKEN_KEY);
    if (!token) {
        return null;
    }

    try {
        const folder = await fileSystem.getEntryForPersistentToken(token);
        if (!folder?.isFolder) {
            throw new Error("保存された出力先はフォルダではありません。");
        }
        return folder;
    } catch (_error) {
        keyValueStore.removeItem(OUTPUT_FOLDER_TOKEN_KEY);
        return null;
    }
}

module.exports = {
    OUTPUT_FOLDER_TOKEN_KEY,
    restoreOutputFolder,
    saveOutputFolder,
};
