export type Location = {
  id: number;
  name: string;
  lat: number;
  lon: number;
  member: string;
  address: string;
  hours: string;
  holidays: string;
  img_url: string;
  // collection state - the frontend is the only writer of these two columns
  stamp: boolean;
  badge: boolean;
};

export type FilterKey = 'stamp_missing' | 'badge_missing';
