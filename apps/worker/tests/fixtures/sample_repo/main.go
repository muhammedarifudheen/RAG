package main

import (
	"fmt"

	geo "example.com/sample/geometry"
)

func NewUnit() *geo.Circle {
	return &geo.Circle{Radius: 1}
}

func main() {
	c := NewUnit()
	fmt.Println(geo.Total(c))
}
