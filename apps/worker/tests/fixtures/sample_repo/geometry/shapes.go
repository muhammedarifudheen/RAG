package geometry

import "math"

type Shape interface {
	Area() float64
}

type Point struct {
	X, Y float64
}

type Circle struct {
	Point
	Radius float64
}

func (c *Circle) Area() float64 {
	return math.Pi * square(c.Radius)
}

func (c *Circle) Scaled() float64 {
	return 2 * c.Area()
}

func square(x float64) float64 {
	return x * x
}

func Total(shapes ...Shape) float64 {
	sum := 0.0
	for _, s := range shapes {
		sum += s.Area()
	}
	return square(sum)
}
