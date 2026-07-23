export const MEMBER_COLORS: Record<string, string> = {
  '高海千歌': '#F0A20B',
  '桜内梨子': '#E9A9E8',
  '松浦果南': '#13E8AE',
  '黒澤ダイヤ': '#F23B4C',
  '渡辺曜': '#49B9F9',
  '津島善子': '#898989',
  '国木田花丸': '#E6D617',
  '小原鞠莉': '#AE58EB',
  '黒澤ルビィ': '#FB75E4',
};

export function colorForMember(member: string): string {
  return MEMBER_COLORS[member] ?? 'black';
}
