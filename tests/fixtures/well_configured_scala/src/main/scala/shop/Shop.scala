package shop

object Shop:
  def total(items: Seq[(String, Int)]): Int = items.map(_._2).sum
