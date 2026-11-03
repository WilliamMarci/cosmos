import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'packaging'))
import reuse_optional


class PublishedReuseTests(unittest.TestCase):
    def test_only_matching_recipes_and_verified_archives_are_reused(self):
        for changed in (False,True):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                (root/'packaging').mkdir()
                for name in ('build_optional.sh','assemble.py'):(root/'packaging'/name).write_bytes(b'recipe')
                buffer=io.BytesIO()
                with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
                    member=tarfile.TarInfo('vendor/pdf/bin/pdfinfo');member.size=7
                    archive.addfile(member,io.BytesIO(b'fixture'))
                data=buffer.getvalue();sources=b'source fixture'
                filename='cosmos-0.2.1-pdf-linux-x86_64-glibc2.28.tar.gz'
                source_name='cosmos-0.2.1-pdf-glibc2.28-sources.tar.gz'
                base=reuse_optional.REPO+'/releases/download/v0.2.1'
                entry=dict(name='pdf',arch='x86_64',glibc_min='2.28',filename=filename,url=base+'/'+filename,size=len(data),sha256=hashlib.sha256(data).hexdigest(),unpacked_size=7)
                def urlopen(request,**kwargs):
                    if isinstance(request,str):return io.BytesIO(b'changed' if changed else b'recipe')
                    return io.BytesIO(json.dumps([dict(tag_name='v0.2.1',draft=False,published_at='now')]).encode())
                def download(url,path,limit):
                    if url.endswith('/components.json'):path.write_text(json.dumps(dict(version='0.2.1',components=[entry])))
                    elif url.endswith('.sha256'):path.write_text(hashlib.sha256(sources).hexdigest()+'  '+source_name+'\n')
                    elif url.endswith(source_name):path.write_bytes(sources)
                    else:path.write_bytes(data)
                with patch.object(reuse_optional,'ROOT',root),patch.object(reuse_optional.urllib.request,'urlopen',side_effect=urlopen),patch.object(reuse_optional,'download',side_effect=download) as fetch:
                    self.assertEqual(reuse_optional.reuse('pdf','2.28'),not changed)
                if changed:fetch.assert_not_called()
                else:self.assertEqual((root/'.build/optional-pdf/stage/vendor/pdf/bin/pdfinfo').read_bytes(),b'fixture')
