/// <reference types="@react-three/fiber" />

declare module "umap-js" {
  export class UMAP {
    constructor(params?: {
      nNeighbors?: number;
      minDist?: number;
      nComponents?: number;
      spread?: number;
    });
    fit(data: number[][]): number[][];
  }
}
