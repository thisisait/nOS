
export interface TaxonomyItem {
  id: string;
  name: string;
  description?: string;
  completed?: boolean;
  questType?: 'download' | 'read' | 'exercise' | 'explore';
  requiredData?: string; // kiwix package, file, etc.
}

export interface TaxonomySubcategory {
  name: string;
  id: string;
  description?: string;
  subcategories?: Record<string, TaxonomySubcategory>;
  items?: TaxonomyItem[];
  unlocked?: boolean;
  progress?: number;
}

export interface TaxonomyCategory {
  name: string;
  id: string;
  description: string;
  subcategories: Record<string, TaxonomySubcategory>;
  unlocked?: boolean;
  progress?: number;
}

export interface TaxonomyData {
  [key: string]: TaxonomyCategory;
}

// Game mapping types
export type GameLevel = 'island' | 'city' | 'building';

export interface GameNode {
  id: string;
  name: string;
  type: GameLevel;
  taxonomyId: string;
  position: { x: number; y: number };
  unlocked: boolean;
  completed: boolean;
  children?: GameNode[];
  items?: TaxonomyItem[]; // Add items property for buildings
}
