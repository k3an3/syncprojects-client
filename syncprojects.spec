# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


a = Analysis(['syncprojects/syncprojects_app.py'],
             pathex=['/Users/keane/dev/syncprojects'],
             binaries=[],
             datas=[('res/benny.icns', 'res')],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='syncprojects',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False , icon='res/benny.icns')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='syncprojects')
app = BUNDLE(coll,
             name='syncprojects.app',
             icon='res/benny.icns',
             bundle_identifier=None)
