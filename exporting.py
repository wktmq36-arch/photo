"""Prepare only the explicitly selected export subdirectories."""
from pathlib import Path
import shutil
import stat


def linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))


def prepare_output(parent, name, sources, notify, outputs=None):
    parent=Path(parent).resolve(strict=True)
    candidate=parent/name
    if candidate.exists() or candidate.is_symlink():
        if linked(candidate):raise ValueError('연결된 폴더는 출력 대상으로 사용할 수 없습니다.')
    destination=candidate.resolve()
    if destination.parent!=parent or destination==parent:raise ValueError('출력 폴더는 선택한 저장 위치 바로 아래여야 합니다.')
    if destination.exists() and not destination.is_dir():raise ValueError('동일한 이름의 파일이 있습니다.')
    if outputs is None:outputs={'cen':True,'uncen':True,'main':True}
    selected=[destination/(name+'_'+kind) for kind in ['cen','uncen','main'] if outputs.get(kind)]
    if not selected:raise ValueError('출력 항목을 하나 이상 선택하세요.')
    existing=[]
    # Validate every exact recursive-delete root before confirming or mutating.
    for target in selected:
        if target.exists() or target.is_symlink():
            if linked(target):raise ValueError('연결된 출력 폴더는 교체할 수 없습니다.')
        resolved=target.resolve()
        if resolved.parent!=destination or resolved==destination:raise ValueError('출력 폴더 범위를 벗어났습니다.')
        for source in sources:
            if Path(source).resolve().is_relative_to(resolved):
                raise ValueError('교체할 출력 폴더 안에 작업 원본이 있습니다. 다른 출력 이름을 사용하세요.')
        if target.exists():
            if not target.is_dir():raise ValueError('출력 폴더와 같은 이름의 파일이 있습니다.')
            existing.append(resolved)
    if existing and not notify(existing):return None
    destination.mkdir(exist_ok=True)
    for target in existing:shutil.rmtree(target)
    return destination
