# Builds dist\RogueLegendBot.exe (one file, game icon, bundled templates/OCR models/skills/changelog).
# Needs: pip install pyinstaller
$r = $PSScriptRoot  # absolute paths: PyInstaller resolves relative ones from --specpath
python -m PyInstaller --noconfirm --onefile --name RogueLegendBot --icon "$r\roguebot\assets\icon.ico" `
    --paths $r --collect-submodules roguebot --collect-data rapidocr `
    --add-data "$r\roguebot\templates;roguebot\templates" --add-data "$r\roguebot\assets;roguebot\assets" `
    --add-data "$r\data\skills.json;data" --add-data "$r\CHANGELOG.md;." `
    --distpath "$r\dist" --workpath "$r\build" --specpath "$r\build" "$r\roguebot\__main__.py"
