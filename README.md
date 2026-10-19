# Photo

Windows용 그림 정리·모자이크 앱. Python + PySide6 + Pillow.

## 실행
배포 ZIP을 모두 풀고 `Photo/Photo.exe`를 실행합니다. `_internal` 폴더도 함께 있어야 합니다.

## 사용
1. WebP, PNG, JPEG 등의 파일 또는 폴더를 창에 드롭합니다. 폴더는 하위 폴더까지 읽습니다.
2. 썸네일 클릭으로 미리보기를 보고, 드래그로 순서를 변경합니다.
3. Ctrl/Shift로 여러 파일 선택 후 Delete를 누르면 목록에서 제외됩니다. 원본은 삭제하지 않습니다.
4. 미리보기에서 사각형을 드래그하면 모자이크가 추가됩니다. 영역을 클릭하고 강도(2~100)를 조절합니다. 값이 클수록 픽셀이 커집니다. 선택 영역 삭제, 원본 비교를 지원합니다.
5. 작업 저장으로 순서와 영역을 JSON에 보관합니다. 원본 파일은 같은 위치에 유지해야 합니다.
6. PNG/WEBP/JPEG를 선택하고 내보냅니다. 새 결과 폴더에 현재 순서대로 001, 002… 저장합니다. JPEG 투명 영역은 흰색으로 합성됩니다. 움직이는 WebP는 첫 프레임만 처리합니다.

## 속도
썸네일과 미리보기는 별도 작업 스레드에서 생성합니다. 최근 16장의 최대 1920px 미리보기를 메모리에 보관하고 앞뒤 이미지를 미리 읽습니다. 최초 파일 읽기는 파일 크기·디스크에 영향을 받습니다. 전체 원본은 내보낼 때 한 장씩 처리합니다.

## 메타데이터
EXIF 방향을 픽셀에 적용하고 RGBA 픽셀 바이트만으로 새 이미지를 생성합니다. EXIF, XMP, ICC, PNG 생성 파라미터 등 원본 메타데이터는 복사하지 않습니다. 출력 후 다시 열어 EXIF 및 알려진 메타데이터 키를 검사합니다. PNG/JPEG/WebP 파일 규격 자체의 필수 헤더는 존재합니다.

결과 이미지에서 제거된 원본 메타데이터를 제공하지 않는다는 의미이며, 원본·백업·작업 JSON·운영체제 임시 데이터의 보안 삭제 기능은 아닙니다. 모자이크 내용의 추측 가능성까지 방지한다는 보장은 없습니다. JSON에는 원본의 로컬 경로가 있으므로 공유하지 마세요. 이미지 픽셀에 직접 그려진 워터마크나 숨겨진 신호를 자동 제거하지 않습니다.

## 개발 / 빌드
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
python -m unittest -v test_photo
python -m PyInstaller --noconfirm --windowed --onedir --name Photo main.py
```
GitHub Actions에서 수동 실행하거나 v로 시작하는 태그를 push하면 Windows 빌드 artifact를 만듭니다. 이미지 및 작업 JSON, 빌드 출력은 소스 저장소에 올리지 않습니다.

Qt/PySide6 및 Pillow 등 의존성의 라이선스는 각 배포 라이선스를 따릅니다.
