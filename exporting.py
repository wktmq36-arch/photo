"""Prepare the exact named output directory for replacement."""
from pathlib import Path
import shutil
import stat


def prepare_output(parent, name, sources, notify):
    parent=Path(parent).resolve(strict=True)
    candidate=parent/name
    if candidate.exists() or candidate.is_symlink():
        attributes=getattr(candidate.lstat(),'st_file_attributes',0)
        if candidate.is_symlink() or attributes & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
            raise ValueError('연결된 폴더는 출력 대상으로 사용할 수 없습니다.')
    destination=candidate.resolve()
    if destination.parent!=parent or destination==parent:
        raise ValueError('출력 폴더는 선택한 저장 위치 바로 아래여야 합니다.')
    for source in sources:
        if Path(source).resolve().is_relative_to(destination):
            raise ValueError('출력 폴더 안에 작업 원본이 있습니다. 원본을 보존하려면 다른 폴더 이름을 지정하세요.')
    if destination.exists():
        if not destination.is_dir():raise ValueError('동일한 이름의 파일이 있습니다.')
        children=list(destination.iterdir())
        # Verify all recursive-delete roots before deleting anything.
        for child in children:
            if not child.resolve().is_relative_to(destination):
                raise ValueError('출력 폴더 외부로 연결된 항목이 있어 비울 수 없습니다.')
        if not notify(destination):return None
        for child in children:
            if child.is_symlink():child.unlink()
            elif child.is_dir():shutil.rmtree(child)
            else:child.unlink()
    else:destination.mkdir()
    return destination
