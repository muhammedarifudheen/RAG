export interface Shape {
  area(): number;
}

export class Circle implements Shape {
  constructor(private radius: number) {}

  area(): number {
    return Math.PI * square(this.radius);
  }
}

export class Disc extends Circle {
  describe(): string {
    return `disc ${this.area()}`;
  }
}

export function square(x: number): number {
  return x * x;
}

export const double = (x: number): number => x * 2;
