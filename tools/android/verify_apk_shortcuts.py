#!/usr/bin/env python3
"""Check shortcut intents after aapt2 has linked and optimized resource paths."""
import argparse
import re
import subprocess


def verify(aapt, apk, application_id):
    resources = subprocess.check_output([str(aapt), 'dump', 'resources', str(apk)], text=True, encoding='utf-8')
    blocks = re.split(r'(?m)^\s*resource\s+', resources)
    shortcuts = [block for block in blocks
                 if re.match(r'0x[0-9a-fA-F]+\s+xml/shortcuts\s*\n', block)]
    if len(shortcuts) != 1:
        raise ValueError('expected exactly one xml/shortcuts resource')
    paths = re.findall(r'\(file\)\s+(\S+)\s+type=XML', shortcuts[0])
    if len(paths) != 1:
        raise ValueError('expected one linked shortcuts XML file')
    # Release resource optimization can shorten res/xml/shortcuts.xml to res/Eq.xml.
    # Resolve its actual path through the resource table, never assume its basename.
    xml = subprocess.check_output([str(aapt), 'dump', 'xmltree', str(apk), '--file', paths[0]], text=True, encoding='utf-8')
    packages = re.findall(r':targetPackage\([^)]*\)="([^"]+)"', xml)
    classes = re.findall(r':targetClass\([^)]*\)="([^"]+)"', xml)
    if packages != [application_id] * 3:
        raise ValueError('launcher shortcuts must target this APK application ID')
    expected_classes = ['org.wwhdrecomp.wwhd.' + name for name in
                        ('ExportSaveActivity', 'SetupActivity', 'ImportSaveActivity')]
    if classes != expected_classes:
        raise ValueError('launcher shortcut target classes changed')
    return paths[0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aapt', required=True)
    parser.add_argument('--apk', required=True)
    parser.add_argument('--application-id', required=True)
    args = parser.parse_args()
    print('Verified launcher shortcuts:', verify(args.aapt, args.apk, args.application_id))
