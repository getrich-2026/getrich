# Licenese Key

iJTkO29NlrZ23X6M5w29Gh_4gShTv46OvOdm9EFZQfKnMg58DCKQBnSV0eay4MoG0ZhzhX_LTms00WMswme83iOk4ag7Z0OzToI04B67QbOWpicDqD7qxcd7TmK6bAKCTHBz-6wuGI7Zdrp9Z9Iop5BSHGqYvAm-nXJ-SsCHfoA=dcrc05HTqctrrjbxZjLDlYqv08eY68tPZGYfO_3PosCUVmbfw4WbyLzS6n9BG5EbP4ZCZ5r89rHrOHYfxY5fL5zOA3SfxO7oDdd3mHhgwPIlGNOKGkQvJhx637sQ2697R-qZThciVWKVD01dD70rCBuhHAIit26fGOhluTipHGQ=



# 安装方法

python环境默认使用uv进行管理。

传统的安装方式：

```sh
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple rqsdk
```

# 初始化代码

参考:

```python
def init_rq(license='Q'):
    """Initialize RiceQuant connection."""
    if license=='Q':
        rq.init('license', 'JTQJAInlhYlzIYybULRXgmPKV-iZyRODGpc0gysKQoKZM_jHl690zu8Z93sfLSw34qlN5FmRFstAW_'
                           'UUR2EtLwQrBEXjg8uQ5FSeHgelzN_BvXGH4b4bKwu8U-gY7CEl64R--tgg-apqSnQQNuaopcY1-nnHSxIbdRxX_wn0f7A=iXy'
                           'a8lXbgfYEgpRfHWC48u128TOizEYe03CwlWHQDPJYQ5AupZHmdvJM3M4-1nx7cL87LjywmCImv4IyK-Nnq4PaqsfSxfrbfoxX'
                           'Tlyd5FaxR3LKPopPqWcE9oyYiQt9LxCePq6p3oJzXMsYXcB8uWFFvqdf-f0GjweNrPXs4Ug=')
    elif license=='L':
        rq.init(
            "tcp://license:"
            "iJTkO29NlrZ23X6M5w29Gh_4gShTv46OvOdm9EFZQfKnMg58DCKQBnSV0eay4MoG0ZhzhX_LTms"
            "00WMswme83iOk4ag7Z0OzToI04B67QbOWpicDqD7qxcd7TmK6bAKCTHBz-6wuGI7Zdrp9Z9Iop5BSH"
            "GqYvAm-nXJ-SsCHfoA=dcrc05HTqctrrjbxZjLDlYqv08eY68tPZGYfO_3PosCUVmbfw4WbyLzS6n9BG5"
            "EbP4ZCZ5r89rHrOHYfxY5fL5zOA3SfxO7oDdd3mHhgwPIlGNOKGkQvJhx637sQ2697R-qZThciVWKVD01dD"
            "70rCBuhHAIit26fGOhluTipHGQ=@rqdatad-pro.ricequant.com:16011"
        )
```

上面这段代码到意思是有两个license，一个是Q的，一个是L的，本质上是可以用同样的方式进行初始化的，这次我们先用L的。

# API 说明

这次我们先处理跨品种通用API，详见网址：https://www.ricequant.com/doc/rqdata/python/generic-api

如果网址打开不，请参考 ./Ricequant Docs.pdf
