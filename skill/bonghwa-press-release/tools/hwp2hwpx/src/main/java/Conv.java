import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwp2hwpx.Hwp2Hwpx;
import kr.dogfoot.hwpxlib.object.HWPXFile;
import kr.dogfoot.hwpxlib.writer.HWPXWriter;

/** 구형 .hwp(HWP 5.0)를 .hwpx로 변환한다. 사용법: java Conv 입력.hwp 출력.hwpx */
public class Conv {
  public static void main(String[] a) throws Exception {
    if (a.length != 2) { System.err.println("사용법: convert.sh 입력.hwp 출력.hwpx"); System.exit(1); }
    HWPFile h = HWPReader.fromFile(a[0]);
    HWPXFile x = Hwp2Hwpx.toHWPX(h);
    HWPXWriter.toFilepath(x, a[1]);
    System.out.println("변환 완료: " + a[1]);
  }
}
