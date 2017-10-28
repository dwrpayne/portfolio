

$(document).ready(function () {
    window.gotdata = 0;
    $("button").click(function () {
        $(this).attr('disabled', 'disabled');
        $(this).html("Refreshing...");
        $.ajax({
            url: 'go',
            data: $(this).attr('class'),
            success: function (data) {
                gotdata = $(data).find('div');
                console.log($(data))
                div_id = $(data).attr('id')
                console.log('#' + div_id)
                var html = $(data).filter('#' + div_id).html();
                console.log(html)
                //$('#' + div_id).html(html);
            }
        });
    });
});